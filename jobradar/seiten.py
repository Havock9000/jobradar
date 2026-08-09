"""Karriereseiten-Watcher.

Holt öffentlich zugängliche Stellenseiten von Arbeitgebern, die keinen Feed
anbieten, und zieht daraus Links, die einem konfigurierten Muster entsprechen.

Rechtlicher Rahmen, den dieses Modul einhält:
  * Nur Seiten ohne Login. Es werden keine Zugangsbeschränkungen umgangen.
  * robots.txt wird vor jedem Abruf geprüft und respektiert.
  * Ein sprechender User-Agent, damit Betreiber den Zugriff zuordnen können.
  * Eine Anfrage pro Seite und Lauf, mit Pause dazwischen.
  * Gespeichert werden nur Titel und Link, kein Volltext-Nachdruck.

Was dieses Modul bewusst NICHT tut: Portale mit Nutzungsbedingungen gegen
automatisierten Zugriff (LinkedIn, Indeed, StepStone) und alles hinter einem
Login. Dort ist der Zugriff vertraglich untersagt, unabhängig davon, ob er
technisch ginge.
"""

from __future__ import annotations

import json
import re
import time
import urllib.robotparser
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

USER_AGENT = ("jobradar/1.0 (persoenliche Stellensuche; "
              "1 Abruf pro Seite und Tag; Kontakt via Repository)")


class RobotsWaechter:
    """Cacht robots.txt je Host und beantwortet die Frage, ob ein Abruf erlaubt ist."""

    def __init__(self, session: requests.Session):
        self.session = session
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def erlaubt(self, url: str) -> tuple[bool, str]:
        host = urlparse(url).netloc
        if host not in self._cache:
            self._cache[host] = self._lade(url)
        parser = self._cache[host]
        if parser is None:
            # Keine robots.txt erreichbar: nach herrschender Praxis erlaubt.
            return True, "keine robots.txt"
        if parser.can_fetch(USER_AGENT, url):
            return True, "robots.txt erlaubt"
        return False, "robots.txt untersagt"

    def _lade(self, url: str):
        teile = urlparse(url)
        robots_url = f"{teile.scheme}://{teile.netloc}/robots.txt"
        try:
            r = self.session.get(robots_url, timeout=15,
                                 headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                return None
        except requests.RequestException:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(r.text.splitlines())
        return parser


def _flach(knoten: Any) -> list[dict]:
    """Zieht alle Objekte aus einem JSON-LD-Baum, egal wie verschachtelt.

    JSON-LD kommt in drei Formen vor: ein Objekt, eine Liste von Objekten,
    oder ein @graph-Container. Alle drei kommen in freier Wildbahn vor.
    """
    if isinstance(knoten, dict):
        ergebnis = [knoten]
        for schluessel in ("@graph", "itemListElement", "item"):
            if schluessel in knoten:
                ergebnis += _flach(knoten[schluessel])
        return ergebnis
    if isinstance(knoten, list):
        ergebnis = []
        for eintrag in knoten:
            ergebnis += _flach(eintrag)
        return ergebnis
    return []


def _ist_jobposting(obj: dict) -> bool:
    typ = obj.get("@type")
    if isinstance(typ, list):
        return any(str(t).lower() == "jobposting" for t in typ)
    return str(typ).lower() == "jobposting"


def _text(wert: Any) -> str:
    """Holt einen Namen aus Feldern, die mal String, mal Objekt sind."""
    if isinstance(wert, str):
        return wert.strip()
    if isinstance(wert, dict):
        for schluessel in ("name", "@value", "addressLocality", "value"):
            if wert.get(schluessel):
                return _text(wert[schluessel])
    if isinstance(wert, list) and wert:
        return _text(wert[0])
    return ""


def _ort_aus(job: dict) -> str:
    ort = job.get("jobLocation")
    if isinstance(ort, list) and ort:
        ort = ort[0]
    if isinstance(ort, dict):
        adresse = ort.get("address")
        if isinstance(adresse, dict):
            teile = [adresse.get("addressLocality"), adresse.get("postalCode")]
            zusammen = " ".join(str(t) for t in teile if t).strip()
            if zusammen:
                return zusammen
        return _text(ort)
    return _text(ort)


def lies_jobposting(suppe: BeautifulSoup) -> list[dict[str, Any]]:
    """Findet JobPosting-Markup (schema.org, JSON-LD) auf einer Seite.

    Das ist dieselbe Struktur, aus der Google for Jobs seine Einträge zieht:
    Google bietet keine API mehr, sondern liest dieses Markup direkt von den
    Arbeitgeberseiten. Wer es ausliest, greift die Quelle statt den Aggregator ab.
    """
    treffer: list[dict[str, Any]] = []
    for block in suppe.find_all("script", attrs={"type": "application/ld+json"}):
        roh = block.string or block.get_text() or ""
        try:
            daten = json.loads(roh)
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _flach(daten):
            if not _ist_jobposting(obj):
                continue
            beschreibung = obj.get("description") or ""
            treffer.append({
                "titel": _text(obj.get("title")),
                "arbeitgeber": _text(obj.get("hiringOrganization")),
                "ort": _ort_aus(obj),
                "veroeffentlicht": (obj.get("datePosted") or "")[:10] or None,
                "frist": (obj.get("validThrough") or "")[:10] or None,
                "beschaeftigung": _text(obj.get("employmentType")),
                "volltext": BeautifulSoup(beschreibung, "html.parser").get_text(" ", strip=True),
            })
    return treffer


class SeitenQuelle:
    def __init__(self, session: requests.Session, pause: float):
        self.session = session
        self.pause = pause
        self.robots = RobotsWaechter(session)
        self.uebersprungen: list[str] = []

    def hole(self, quelle: dict[str, Any]) -> list[dict[str, Any]]:
        url = quelle["url"]

        erlaubt, grund = self.robots.erlaubt(url)
        if not erlaubt:
            self.uebersprungen.append(f"{quelle['label']}: {grund}")
            return []

        try:
            r = self.session.get(url, timeout=30,
                                 headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
        except requests.RequestException as exc:
            self.uebersprungen.append(f"{quelle['label']}: {exc}")
            return []
        time.sleep(self.pause)

        suppe = BeautifulSoup(r.text, "html.parser")
        bereich = suppe
        if quelle.get("bereich"):
            treffer = suppe.select_one(quelle["bereich"])
            if treffer:
                bereich = treffer

        muster = re.compile(quelle["link_muster"], re.IGNORECASE)
        ausschluss = (re.compile(quelle["link_ausschluss"], re.IGNORECASE)
                      if quelle.get("link_ausschluss") else None)

        gesehen: set[str] = set()
        eintraege: list[dict[str, Any]] = []

        for a in bereich.find_all("a", href=True):
            href = a["href"].strip()
            titel = " ".join(a.get_text(" ", strip=True).split())
            if not titel or len(titel) < 6:
                continue
            voll = urljoin(url, href)
            if not muster.search(voll) and not muster.search(titel):
                continue
            if ausschluss and (ausschluss.search(voll) or ausschluss.search(titel)):
                continue
            if voll in gesehen:
                continue
            gesehen.add(voll)
            eintraege.append({
                "id": f"seite:{voll}",
                "refnr": None,
                "quelle": quelle["label"],
                "titel": titel[:180],
                "arbeitgeber": quelle.get("arbeitgeber", quelle["label"]),
                "ort": quelle.get("ort", ""),
                "plz": "",
                "entfernung_km": quelle.get("entfernung_km"),
                "veroeffentlicht": None,
                "frist": None,
                "eintritt": None,
                "url": voll,
                "archetyp": quelle.get("archetyp", "medienproduktion"),
                "treffer_begriff": quelle["label"],
                # Ohne JSON-LD laeuft das Screening nur ueber den Titel.
                "_volltext": titel,
                "_strukturiert": False,
            })

        # Manche Uebersichtsseiten tragen das Markup schon selbst.
        self._reichere_aus_seite_an(suppe, eintraege)

        # Detailseiten nachladen, wo konfiguriert. Google-Richtlinie: das Markup
        # sitzt auf der Einzelanzeige, nicht auf der Uebersicht.
        if quelle.get("details_folgen"):
            grenze = int(quelle.get("max_details", 15))
            self._folge_details(eintraege[:grenze], quelle["label"])

        return eintraege

    @staticmethod
    def _reichere_aus_seite_an(suppe: BeautifulSoup,
                               eintraege: list[dict[str, Any]]) -> None:
        jobs = lies_jobposting(suppe)
        if len(jobs) != 1 or len(eintraege) != 1:
            return
        _uebernimm(jobs[0], eintraege[0])

    def _folge_details(self, eintraege: list[dict[str, Any]], label: str) -> None:
        for eintrag in eintraege:
            erlaubt, grund = self.robots.erlaubt(eintrag["url"])
            if not erlaubt:
                self.uebersprungen.append(f"{label} (Detailseite): {grund}")
                continue
            try:
                r = self.session.get(eintrag["url"], timeout=30,
                                     headers={"User-Agent": USER_AGENT})
                if r.status_code != 200:
                    continue
            except requests.RequestException:
                continue
            time.sleep(self.pause)

            suppe = BeautifulSoup(r.text, "html.parser")
            jobs = lies_jobposting(suppe)
            if jobs:
                _uebernimm(jobs[0], eintrag)


def _uebernimm(job: dict[str, Any], eintrag: dict[str, Any]) -> None:
    """Ueberschreibt geratene Felder mit den strukturierten Angaben."""
    if job.get("titel"):
        eintrag["titel"] = job["titel"][:180]
    if job.get("arbeitgeber"):
        eintrag["arbeitgeber"] = job["arbeitgeber"]
    if job.get("ort"):
        eintrag["ort"] = job["ort"]
    if job.get("veroeffentlicht"):
        eintrag["veroeffentlicht"] = job["veroeffentlicht"]
    if job.get("frist"):
        eintrag["frist"] = job["frist"]
    if job.get("volltext"):
        eintrag["_volltext"] = job["volltext"]
    eintrag["_strukturiert"] = True


def pruefe(url: str, link_muster: str = r"stelle|job|karriere|ausschreibung") -> None:
    """Diagnosehilfe: zeigt, ob eine Seite serverseitig gerendert wird und was
    das Linkmuster dort findet.

    Aufruf:  python -m jobradar.seiten <URL> [muster]
    """
    session = requests.Session()
    waechter = RobotsWaechter(session)
    erlaubt, grund = waechter.erlaubt(url)
    print(f"robots.txt: {grund}")
    if not erlaubt:
        return

    r = session.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    print(f"HTTP {r.status_code}, {len(r.text)} Zeichen")

    suppe = BeautifulSoup(r.text, "html.parser")
    alle = suppe.find_all("a", href=True)
    muster = re.compile(link_muster, re.IGNORECASE)
    treffer = [(" ".join(a.get_text(' ', strip=True).split()), urljoin(url, a["href"]))
               for a in alle
               if muster.search(urljoin(url, a["href"]))
               or muster.search(a.get_text(" ", strip=True))]

    jobs = lies_jobposting(suppe)
    if jobs:
        print(f"\nJobPosting-Markup gefunden: {len(jobs)} Eintrag/Eintraege")
        for j in jobs[:3]:
            print(f"  · {j['titel']} | {j['arbeitgeber']} | {j['ort']}")
            print(f"    veroeffentlicht {j['veroeffentlicht']} · Frist {j['frist']} "
                  f"· Volltext {len(j['volltext'])} Zeichen")
        print("  -> details_folgen: true lohnt sich hier.")
    else:
        print("\nKein JobPosting-Markup auf dieser Seite. Bei Uebersichtsseiten "
              "normal — das Markup sitzt meist auf der Einzelanzeige. Pruefe "
              "eine davon einzeln.")

    print(f"{len(alle)} Links gesamt, {len(treffer)} passen auf /{link_muster}/")
    if not treffer and len(r.text) > 5000:
        print("\nHinweis: viel HTML, aber keine Treffer. Die Seite laedt ihre "
              "Stellenliste vermutlich per JavaScript nach. Dann ist sie mit "
              "diesem Modul nicht auslesbar — pruefe, ob der Anbieter einen "
              "Feed oder eine JSON-Schnittstelle hat.")
    for titel, link in treffer[:25]:
        print(f"  · {titel[:80]}\n    {link}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Aufruf: python -m jobradar.seiten <URL> [link_muster]")
        raise SystemExit(1)
    pruefe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else
           r"stelle|job|karriere|ausschreibung")
