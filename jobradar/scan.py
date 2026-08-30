"""Jobradar – sammelt Stellenanzeigen aus der BA-Jobsuche und service.bund.de,
screent sie gegen die eigenen Ausschlusskriterien und schreibt data/jobs.json.

Aufruf:  python -m jobradar.scan
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

from jobradar.dedupe import zusammenfuehren
from jobradar.erreichbarkeit import Arbeitsmodell, Fahrzeit, Regelwerk
from jobradar.lauf import FILTERGRUENDE, _leerer_zaehler, bewerte_eintrag
from jobradar.merkmale import Entgelt
from jobradar.passung import Passung

BA_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
# Suche laeuft auf v6. v4/app/jobs und v5 antworten seit 2026 mit
# 403 "No match found for request" — das Gateway routet die Pfade nicht mehr.
# Der Detail-Abruf haengt weiterhin auf v4; v6/jobdetails existiert nicht.
BA_SEARCH = f"{BA_BASE}/v6/jobs"
BA_DETAIL = f"{BA_BASE}/v4/jobdetails"
# Schluessel, unter dem die Trefferliste in der Suchantwort steht.
BA_LISTE = "ergebnisliste"
BA_HEADERS = {
    "X-API-Key": "jobboerse-jobsuche",
    "User-Agent": "jobradar/1.0 (persoenliche Stellensuche)",
    "Accept": "application/json",
}
POSTING_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
# Nur dieser Ordner geht nach GitHub Pages. Alles andere im Repository
# (config.yaml, CLAUDE.md, EINRICHTUNG.md) bleibt draussen — es enthaelt
# Suchstrategie und persoenliches Profil und gehoert nicht ins Web.
SITE = ROOT / "site"
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Hilfen
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def strip_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    return WS_RE.sub(" ", html.unescape(text)).strip()


def today() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value: str | None) -> str | None:
    """Normalisiert diverse Datumsformate auf YYYY-MM-DD."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z",
                "%d.%m.%Y", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(value[:len(fmt) + 8] if "%z" in fmt else value[:len(fmt)],
                                     fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return m.group(0)
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def age_days(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (today() - d).days


# --------------------------------------------------------------------------- #
# Screening
# --------------------------------------------------------------------------- #

class Ausschluss:
    """Prüft ausschließlich den Stellentitel gegen die Ausschlussmuster.

    Bewusst nicht gegen den Volltext: eine Anzeige, die Social Media als eine
    Aufgabe unter vielen nennt, soll nicht rausfallen.
    """

    def __init__(self, muster: list[str] | None):
        self.muster = [re.compile(p, re.IGNORECASE) for p in muster or []]
        self.gezaehlt = 0

    def greift(self, titel: str) -> str | None:
        for pat in self.muster:
            if pat.search(titel or ""):
                self.gezaehlt += 1
                return pat.pattern
        return None


# Umkreis, Passung (titelbasiert) und RemotePruefer sind am 11.08.2026
# entfallen. Der Titelfilter urteilte ueber die Berufsbezeichnung, und die
# Umkreispruefung ueber Luftlinie — beides zu grob. An ihre Stelle treten
# jobradar.passung (Scoring am Anzeigentext) und jobradar.erreichbarkeit
# (Fahrzeit, Arbeitsmodell, Wochenbudget).


class Screener:
    def __init__(self, rules: dict[str, Any]):
        def compile_all(patterns):
            return [re.compile(p, re.IGNORECASE) for p in patterns or []]

        self.studium_hart = compile_all(rules.get("studium", {}).get("hart"))
        self.studium_weich = compile_all(rules.get("studium", {}).get("weich"))
        self.ehrenamt = compile_all(rules.get("ehrenamtslogik"))
        self.befristung = compile_all(rules.get("befristung"))

    @staticmethod
    def _first_hit(patterns, text: str) -> str | None:
        for pat in patterns:
            m = pat.search(text)
            if m:
                start = max(0, m.start() - 60)
                end = min(len(text), m.end() + 60)
                return f"…{text[start:end].strip()}…"
        return None

    def run(self, text: str, vertragsdauer: str | None = None) -> dict[str, Any]:
        """Screent den Volltext. `vertragsdauer` ist die strukturierte Angabe
        der BA (UNBEFRISTET/BEFRISTET) und schlaegt das Regex-Muster, wo sie
        vorliegt — die Regex raet, dieses Feld weiss es. Der Beleg nennt die
        Herkunft, damit im Dashboard sichtbar bleibt, worauf das Urteil beruht.
        """
        hart = self._first_hit(self.studium_hart, text)
        weich = self._first_hit(self.studium_weich, text)

        if hart and weich:
            studium = {"stufe": "weich", "beleg": weich}
        elif hart:
            studium = {"stufe": "hart", "beleg": hart}
        else:
            studium = {"stufe": "offen", "beleg": None}

        ehrenamt_beleg = self._first_hit(self.ehrenamt, text)
        befristung_beleg = self._first_hit(self.befristung, text)
        befristet = bool(befristung_beleg)

        if vertragsdauer in ("BEFRISTET", "UNBEFRISTET"):
            befristet = vertragsdauer == "BEFRISTET"
            befristung_beleg = f"strukturierte Angabe der BA: {vertragsdauer}"

        return {
            "studium": studium,
            "ehrenamtslogik": {
                "getroffen": bool(ehrenamt_beleg),
                "beleg": ehrenamt_beleg,
            },
            "befristung": {
                "getroffen": befristet,
                "beleg": befristung_beleg,
            },
            "textlaenge": len(text),
        }


# --------------------------------------------------------------------------- #
# Quelle 1: Bundesagentur für Arbeit
# --------------------------------------------------------------------------- #

class QuellenAusfall(RuntimeError):
    """Eine Quelle war komplett nicht erreichbar.

    Wichtig genug fuer eine eigene Ausnahme: Ohne sie ist ein Totalausfall
    nicht von "alle Anzeigen zurueckgezogen" zu unterscheiden. Der Merge wuerde
    jede bekannte Stelle als `entfernt` markieren, das Dashboard zeigte einen
    leeren Bestand, und der Lauf endete mit Erfolg. Stattdessen: abbrechen,
    bevor irgendetwas geschrieben wird, und den Zustand unangetastet lassen.
    """


class BundesagenturQuelle:
    def __init__(self, cfg: dict[str, Any], session: requests.Session):
        self.session = session
        self.versuche = 0
        self.fehler = 0
        self.wo = cfg["standort"]["wo"]
        self.umkreis = cfg["standort"]["umkreis_km"]
        lauf = cfg["lauf"]
        self.size = min(int(lauf.get("treffer_pro_begriff", 100)), 100)
        self.veroeffentlicht_seit = int(lauf.get("veroeffentlicht_seit_tagen", 30))
        self.pause = float(lauf.get("pause_sekunden", 0.6))

    def suche(self, begriff: str, bundesweit: bool = False) -> list[dict[str, Any]]:
        """`bundesweit=True` laesst `wo`/`umkreis` weg. Die API sucht dann in
        ganz Deutschland — der Weg, um Remote-Stellen ausserhalb des
        Pendelradius ueberhaupt zu sehen. Geprueft: 'Videograf' liefert mit
        Ortsangabe 1 Treffer, ohne 17.
        """
        params = {
            "was": begriff,
            "angebotsart": 1,          # 1 = Arbeit (nicht Ausbildung/Praktikum)
            "veroeffentlichtseit": min(self.veroeffentlicht_seit, 100),
            "page": 1,
            "size": self.size,
            "pav": "false",            # keine Personalvermittler
        }
        if not bundesweit:
            params["wo"] = self.wo
            params["umkreis"] = self.umkreis
        self.versuche += 1
        try:
            r = self.session.get(BA_SEARCH, headers=BA_HEADERS,
                                 params=params, timeout=30)
            r.raise_for_status()
        except requests.RequestException as exc:
            self.fehler += 1
            log(f"  ! BA-Suche '{begriff}' fehlgeschlagen: {exc}")
            return []
        time.sleep(self.pause)
        payload = r.json() or {}
        treffer = payload.get(BA_LISTE)
        if treffer is None:
            # Genau so ist die Quelle stillschweigend ausgefallen: HTTP 200,
            # Feld umbenannt, null Treffer, kein Fehler. Darum laut werden.
            log(f"  ! BA-Antwort ohne '{BA_LISTE}' — Schluessel vorhanden: "
                f"{sorted(payload)}")
            return []
        return treffer

    def details(self, refnr: str) -> str:
        """Volltext der Anzeige. Leer, wenn nicht abrufbar."""
        encoded = base64.b64encode(refnr.encode()).decode()
        try:
            r = self.session.get(f"{BA_DETAIL}/{encoded}", headers=BA_HEADERS,
                                 timeout=30)
            if r.status_code != 200:
                return ""
        except requests.RequestException:
            return ""
        time.sleep(self.pause)
        try:
            payload = r.json() or {}
        except ValueError:
            return ""
        parts = [
            payload.get("stellenangebotsBeschreibung"),
            payload.get("stellenangebotsTitel"),
            payload.get("hauptberuf"),
        ]
        text = strip_html(" ".join(p for p in parts if p))
        if not text:
            log(f"  ! Detailantwort ohne Beschreibungstext — Schluessel: "
                f"{sorted(payload)[:12]}")
        return text

    @staticmethod
    def normalisiere(roh: dict[str, Any], archetyp: str, begriff: str) -> dict[str, Any] | None:
        """Uebersetzt einen v6-Treffer in das interne Format.

        Bewusst ohne Rueckfallebene auf die alten v4-Namen: eine stille
        Rueckfallebene ist der Grund, warum der Bruch monatelang unbemerkt
        blieb. Aendert die BA die Namen erneut, sollen die Felder sichtbar
        leer sein statt heimlich aus einer Altlast gefuellt.
        """
        refnr = roh.get("referenznummer")
        if not refnr:
            return None
        adresse = (roh.get("stellenlokationen") or [{}])[0].get("adresse") or {}
        zeitraum = roh.get("veroeffentlichungszeitraum") or {}
        eintritt = roh.get("eintrittszeitraum") or {}
        return {
            "id": f"ba:{refnr}",
            "refnr": refnr,
            "quelle": "Bundesagentur für Arbeit",
            "titel": (roh.get("stellenangebotsTitel")
                      or roh.get("hauptberuf") or "").strip(),
            "arbeitgeber": (roh.get("firma") or "").strip(),
            "ort": adresse.get("ort") or "",
            "plz": adresse.get("plz") or "",
            # entfernung steht in v6 auf oberster Ebene, nicht mehr im Ort.
            "entfernung_km": roh.get("entfernung"),
            "veroeffentlicht": parse_date(roh.get("datumErsteVeroeffentlichung")
                                          or zeitraum.get("von")),
            "frist": None,
            "eintritt": parse_date(eintritt.get("von")),
            "url": roh.get("externeUrl") or POSTING_URL.format(refnr=refnr),
            "archetyp": archetyp,
            "treffer_begriff": begriff,
            # Strukturierte Angaben der BA. Verlaesslicher als die Regex-Muster,
            # darum als eigene Felder aufgehoben (siehe Screener.run).
            "vertragsdauer": roh.get("vertragsdauer"),
            "quereinstieg": roh.get("quereinstiegGeeignet"),
        }


# --------------------------------------------------------------------------- #
# Quelle 2: service.bund.de (RSS)
# --------------------------------------------------------------------------- #

class RssQuelle:
    def __init__(self, session: requests.Session, pause: float):
        self.session = session
        self.pause = pause
        self.versuche = 0
        self.fehler = 0

    def hole(self, quelle: dict[str, Any]) -> list[dict[str, Any]]:
        import feedparser

        self.versuche += 1
        try:
            r = self.session.get(quelle["url"], timeout=30,
                                 headers={"User-Agent": BA_HEADERS["User-Agent"]})
            r.raise_for_status()
        except requests.RequestException as exc:
            self.fehler += 1
            log(f"  ! RSS '{quelle['label']}' fehlgeschlagen: {exc}")
            return []
        time.sleep(self.pause)

        feed = feedparser.parse(r.content)
        eintraege = []
        for e in feed.entries:
            link = getattr(e, "link", "") or ""
            if not link:
                continue
            summary = strip_html(getattr(e, "summary", "") or "")
            titel = strip_html(getattr(e, "title", "") or "")
            ort = self._ort(summary)
            eintraege.append({
                "id": f"rss:{link}",
                "refnr": None,
                "quelle": quelle["label"],
                "titel": titel,
                "arbeitgeber": self._arbeitgeber(summary, titel),
                "ort": ort,
                "plz": self._plz(ort),
                "entfernung_km": None,
                "veroeffentlicht": parse_date(getattr(e, "published", None)),
                # Die Frist steht in der Zusammenfassung — bisher weggeworfen.
                "frist": self._frist(summary),
                "eintritt": None,
                "url": link,
                "archetyp": quelle.get("archetyp", "pressestelle"),
                "treffer_begriff": quelle["label"],
                "_volltext": f"{titel} {summary}",
                # Die Zusammenfassung ist reine Metadatenzeile (Arbeitgeber,
                # Ort, Frist) und enthaelt keinen Satz aus der Anzeige. Das
                # Screening laeuft hier also auf dem Titel — unabhaengig davon,
                # wie lang der Titel zufaellig ist.
                "_volltext_echt": False,
            })
        return eintraege

    # Die Zusammenfassung ist eine einzige Zeile ohne Trennzeichen:
    #   "Arbeitgeber: Landkreis Oder-Spree Ort: 15848 Beeskow
    #    Bewerbungsfrist: 06.09.2026 00:00 Veröffentlichungsende: 07.09.2026"
    # Eine Laengenbegrenzung wie [^|;\n]{3,80} laeuft darum ueber die
    # Feldgrenze hinweg. Stattdessen bis zum naechsten bekannten Feldnamen.
    FELDER = ("Arbeitgeber", "Einsatzort", "Dienstort", "Ort",
              "Bewerbungsfrist", "Veröffentlichungsende", "Veroeffentlichungsende")

    @classmethod
    def _feld(cls, summary: str, *namen: str) -> str:
        stopp = "|".join(f"{f}\\s*:" for f in cls.FELDER)
        for name in namen:
            m = re.search(rf"{name}\s*:\s*(.*?)(?=\s*(?:{stopp})|$)", summary)
            if m and m.group(1).strip():
                return m.group(1).strip()
        return ""

    @classmethod
    def _arbeitgeber(cls, summary: str, titel: str) -> str:
        return cls._feld(summary, "Arbeitgeber")

    @classmethod
    def _ort(cls, summary: str) -> str:
        return cls._feld(summary, "Einsatzort", "Dienstort", "Ort")

    @classmethod
    def _frist(cls, summary: str) -> str | None:
        return parse_date(cls._feld(summary, "Bewerbungsfrist"))

    @staticmethod
    def _plz(ort: str) -> str:
        m = re.search(r"\b(\d{5})\b", ort)
        return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# Lauf
# --------------------------------------------------------------------------- #

def lade_zustand(pfad: Path) -> dict[str, Any]:
    if not pfad.exists():
        return {"stellen": {}, "laeufe": []}
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log("  ! Zustand unlesbar, starte neu")
        return {"stellen": {}, "laeufe": []}


def _sammle(cfg: dict[str, Any], session: requests.Session,
            ba: "BundesagenturQuelle", ausschluss: "Ausschluss",
            arbeitsmodell: Arbeitsmodell) -> tuple[list[dict[str, Any]], Any, Any]:
    """Alle Quellen einsammeln. Noch ohne Bewertung, ohne Filter.

    Der Titel-Ausschluss wird hier NUR angewendet, wenn er in der Config als
    hart markiert ist. Standardmäßig ist er weich und wirkt allein als
    Abwertung im Score.
    """
    hart = bool(cfg.get("ausschluss_titel_hart"))
    roh: list[dict[str, Any]] = []
    gesehen: set[str] = set()

    def nimm(eintrag: dict[str, Any] | None) -> None:
        if not eintrag or eintrag["id"] in gesehen:
            return
        if hart and ausschluss.greift(eintrag["titel"]):
            return
        if not hart:
            ausschluss.greift(eintrag["titel"])   # nur zählen
        gesehen.add(eintrag["id"])
        roh.append(eintrag)

    for archetyp in cfg.get("archetypen", []):
        log(f"» {archetyp['label']}")
        for begriff in archetyp.get("begriffe", []):
            treffer = ba.suche(begriff)
            log(f"  · '{begriff}': {len(treffer)}")
            for r in treffer:
                nimm(BundesagenturQuelle.normalisiere(r, archetyp["id"], begriff))

    if ba.versuche and ba.fehler == ba.versuche:
        raise QuellenAusfall(
            f"Alle {ba.versuche} BA-Abfragen fehlgeschlagen. Entweder ist der "
            f"Endpunkt erneut umgezogen ({BA_SEARCH}) oder diese IP wird "
            f"abgewiesen — GitHub-Runner laufen in Azure-Rechenzentren, die "
            f"von Behoerden-APIs oft gesperrt sind.")

    # Bundesweiter Zweitlauf für echte Remote-Stellen. Die Fahrzeitregel lässt
    # remote unbegrenzt zu, also lohnt der Blick über den Pendelradius hinaus.
    remote_cfg = cfg.get("remote") or {}
    if remote_cfg.get("aktiv"):
        log("» Remote-Suche (bundesweit)")
        kandidaten: dict[str, dict[str, Any]] = {}
        for archetyp in cfg.get("archetypen", []):
            for begriff in archetyp.get("begriffe", []):
                for r in ba.suche(begriff, bundesweit=True):
                    if not r.get("homeofficemoeglich"):
                        continue
                    e = BundesagenturQuelle.normalisiere(
                        r, archetyp["id"], begriff)
                    if not e or e["id"] in gesehen or e["id"] in kandidaten:
                        continue
                    kandidaten[e["id"]] = e
        log(f"  · {len(kandidaten)} Kandidaten mit Homeoffice-Kennzeichen")
        geprueft = erkannt = 0
        for e in list(kandidaten.values())[:int(remote_cfg.get("max_details", 400))]:
            volltext = ba.details(e["refnr"])
            geprueft += 1
            if arbeitsmodell.bestimme(volltext)["modell"] != "remote":
                continue
            e["_volltext"] = volltext
            e["_volltext_echt"] = True
            erkannt += 1
            nimm(e)
        log(f"  · {geprueft} Volltexte geprueft, {erkannt} sind echt remote")

    rss = RssQuelle(session, float(cfg["lauf"].get("pause_sekunden", 0.6)))
    for quelle in cfg.get("rss_quellen", []):
        log(f"» RSS: {quelle['label']}")
        eintraege = rss.hole(quelle)
        for e in eintraege:
            nimm(e)
        log(f"  · {len(eintraege)} im Feed")

    if rss.versuche and rss.fehler == rss.versuche:
        raise QuellenAusfall(
            f"Alle {rss.versuche} RSS-Feeds fehlgeschlagen. Feed-URLs in "
            f"config.yaml pruefen oder service.bund.de ist gerade weg.")

    from jobradar.jobspy_quelle import JobSpyQuelle
    js = JobSpyQuelle(cfg, log)
    if js.aktiv:
        log("» JobSpy")
        for archetyp in cfg.get("archetypen", []):
            for begriff in archetyp.get("begriffe", []):
                for r in js.suche(begriff):
                    nimm(JobSpyQuelle.normalisiere(r, archetyp["id"], begriff))
        log(f"  · {js.versuche} Abfragen, {js.fehler} fehlgeschlagen")

    from jobradar.seiten import SeitenQuelle
    seiten = SeitenQuelle(session, float(cfg["lauf"].get("pause_sekunden", 0.6)))
    for quelle in cfg.get("seiten_quellen", []):
        treffer = seiten.hole(quelle)
        log(f"» Seite: {quelle['label']}: {len(treffer)}")
        for e in treffer:
            nimm(e)
    for hinweis in seiten.uebersprungen:
        log(f"  ! übersprungen — {hinweis}")

    return roh, seiten, ba


def scanne(cfg: dict[str, Any], zustand: dict[str, Any],
           nur_offline: bool = False) -> dict[str, Any]:
    bekannt: dict[str, Any] = zustand.get("stellen", {})
    lauf_zeit = today().strftime("%Y-%m-%dT%H:%M:%SZ")

    if nur_offline:
        # Nur neu rendern: Bestand unverändert lassen, keinen Lauf protokollieren.
        return zustand

    screener = Screener(cfg.get("screening", {}))
    ausschluss = Ausschluss(cfg.get("ausschluss_titel"))
    arbeitsmodell = Arbeitsmodell(cfg)
    regelwerk = Regelwerk(cfg)
    passung = Passung(cfg)
    entgelt = Entgelt(cfg)

    session = requests.Session()
    fahrzeit = Fahrzeit(cfg, ROOT, session)
    ba = BundesagenturQuelle(cfg, session)

    roh, seiten, ba = _sammle(cfg, session, ba, ausschluss, arbeitsmodell)
    log(f"» {len(roh)} Anzeigen eingesammelt")

    # --- Dedupe VOR dem Screening: teure Schritte nur einmal je Stelle -----
    schwelle = float((cfg.get("dedupe") or {}).get("titel_aehnlichkeit", 0.82))
    roh, doppelt = zusammenfuehren(roh, schwelle)
    log(f"» {doppelt} Duplikate zusammengeführt, {len(roh)} verbleiben")

    # Volltexte fuer neue Anzeigen holen – und einmalig fuer bekannte, denen
    # der Text noch fehlt. Ohne diesen Nachzug haetten alle Eintraege aus der
    # Zeit vor dem Umbau dauerhaft "ohne Beschreibung" gestanden: sie gelten
    # als bekannt, wurden also nie nachgeladen, und ohne Text gibt es keinen
    # Score. Das faellt genau einmal an.
    def braucht_text(e):
        if "_volltext" in e:
            return False
        alt_eintrag = bekannt.get(e["id"])
        if alt_eintrag is None:
            return True
        return not (alt_eintrag.get("_text") or "").strip()

    neu = [e for e in roh if braucht_text(e)]
    log(f"» Volltext für {len(neu)} neue Anzeigen")
    for eintrag in neu:
        eintrag["_volltext"] = ba.details(eintrag["refnr"]) if eintrag["refnr"] else ""
        eintrag["_volltext_echt"] = bool(eintrag["_volltext"])

    zaehler = _leerer_zaehler()
    ohne_text = 0
    stellen: dict[str, Any] = {}

    for eintrag in roh:
        eid = eintrag["id"]
        volltext = eintrag.pop("_volltext", "") or ""
        eintrag.pop("_volltext_echt", None)
        eintrag.pop("_strukturiert", None)

        if eid in bekannt:
            # Bekanntes behalten, aber neu bewerten: sonst erreicht eine
            # Korrektur an Mustern oder Gewichten den Bestand nie.
            alt = bekannt[eid]
            volltext = volltext or alt.get("_text", "")
            alt.update({k: v for k, v in eintrag.items()
                        if k in ("titel", "arbeitgeber", "ort", "plz",
                                 "entfernung_km", "url", "veroeffentlicht",
                                 "frist", "auch_gefunden_bei")
                        and v not in (None, "", [])})
            alt["zuletzt_gesehen"] = lauf_zeit
            alt["neu"] = False
            alt.pop("entfernt", None)
            eintrag = alt
        else:
            eintrag["erstmals_gesehen"] = lauf_zeit
            eintrag["zuletzt_gesehen"] = lauf_zeit
            eintrag["neu"] = True
            eintrag["gesichtet"] = False

        # Volltext aufheben, damit spätere Läufe ohne Netzabruf neu bewerten
        # können. Ohne das wäre jede Musteränderung wirkungslos für Bekanntes.
        if volltext:
            eintrag["_text"] = volltext
        else:
            volltext = eintrag.get("_text", "")
        if not volltext.strip():
            ohne_text += 1

        bewerte_eintrag(eintrag, volltext, screener=screener,
                        arbeitsmodell=arbeitsmodell, fahrzeit=fahrzeit,
                        regelwerk=regelwerk, passung=passung, entgelt=entgelt,
                        cfg=cfg, zaehler=zaehler)
        stellen[eid] = eintrag

    fahrzeit.sichern()

    # Verschwundene Anzeigen behalten, bis sie verfallen.
    verfall = int(cfg["lauf"].get("verfall_tage", 60))
    for eid, alt in bekannt.items():
        if eid in stellen:
            continue
        alter = age_days(parse_date(alt.get("zuletzt_gesehen")))
        if alter is not None and alter > verfall:
            continue
        alt["neu"] = False
        alt["entfernt"] = True
        stellen[eid] = alt

    sichtbar = sum(1 for s in stellen.values()
                   if not s.get("gefiltert") and not s.get("entfernt"))
    log(f"» ausgefiltert: " + ", ".join(f"{g} {zaehler[g]}" for g in FILTERGRUENDE))
    log(f"» {ohne_text} ohne Beschreibung (Status unbekannt, kein Score)")
    log(f"» {sichtbar} in der Standardansicht")

    laeufe = zustand.get("laeufe", [])[-29:]
    laeufe.append({
        "zeit": lauf_zeit,
        "gefunden": len(roh),
        "neu": sum(1 for s in stellen.values() if s.get("neu")),
        "gesamt": len(stellen),
        "sichtbar": sichtbar,
        "zusammengefuehrt": doppelt,
        "ohne_beschreibung": ohne_text,
        "titelmuster_getroffen": ausschluss.gezaehlt,
        "gefiltert": dict(zaehler),
        "fahrzeit_api_aufrufe": fahrzeit.api_aufrufe,
        "uebersprungen": seiten.uebersprungen,
    })

    return {"stellen": stellen, "laeufe": laeufe}


def main() -> int:
    ap = argparse.ArgumentParser(description="Jobradar-Lauf")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--offline", action="store_true",
                    help="Keine Netzabfragen, nur Dashboard aus vorhandenem Zustand neu bauen")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    DATA.mkdir(parents=True, exist_ok=True)
    zustand_pfad = DATA / "jobs.json"

    zustand = lade_zustand(zustand_pfad)
    try:
        neuer_zustand = scanne(cfg, zustand, nur_offline=args.offline)
    except QuellenAusfall as exc:
        log(f"✗ ABBRUCH: {exc}")
        log("  data/jobs.json bleibt unveraendert — lieber ein alter Bestand "
            "als ein Dashboard, das faelschlich 'alles entfernt' meldet.")
        return 1
    zustand_pfad.write_text(
        json.dumps(neuer_zustand, ensure_ascii=False, indent=2),
        encoding="utf-8")

    from jobradar.render import baue_dashboard
    SITE.mkdir(parents=True, exist_ok=True)
    ziel = SITE / "index.html"
    baue_dashboard(cfg, neuer_zustand, ziel)

    letzter = neuer_zustand["laeufe"][-1]
    log(f"✓ {letzter['gesamt']} Stellen im Bestand, {letzter['neu']} neu → {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
