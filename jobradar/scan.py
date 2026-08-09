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


class Umkreis:
    """Ortsfilter fuer Quellen ohne eigenen Umkreisparameter.

    Die BA-Suche filtert selbst ueber `wo`/`umkreis`. Die RSS-Feeds von
    service.bund.de tun das nicht — sie liefern bundesweit. Ohne diesen Filter
    stehen Stellen aus Beeskow und Hildesheim im Dashboard.

    Gefiltert wird ueber PLZ-Praefixe statt echter Entfernung: die Feeds
    liefern nur "Ort: 15848 Beeskow", keine Koordinaten, und eine
    Geocoding-Abfrage je Anzeige waere ein Netzabruf pro Eintrag. Die Praefixe
    stehen in config.yaml und sind damit deine Entscheidung, nicht meine.
    """

    def __init__(self, cfg: dict[str, Any]):
        praefixe = (cfg.get("standort") or {}).get("plz_praefixe") or []
        self.praefixe = tuple(str(p).strip() for p in praefixe if str(p).strip())
        self.verworfen = 0
        self.ohne_plz: list[str] = []

    def drin(self, eintrag: dict[str, Any]) -> bool:
        """Eine Regel fuer alle Quellen — auch fuer die BA.

        Die BA filtert zwar selbst ueber `wo`/`umkreis`, aber 60 km Luftlinie
        reichen bis Bonn und Koeln. Sich auf ihre Vorfilterung zu verlassen
        heisst, genau die Grenze zu uebernehmen, die zu weit ist.

        Ohne PLZ ist nicht entscheidbar. Diese Faelle fliegen raus, werden aber
        einzeln protokolliert — sonst verschwindet womoeglich eine Stelle vor
        der Haustuer, nur weil die Quelle die PLZ weggelassen hat.
        """
        if not self.praefixe:
            return True
        plz = str(eintrag.get("plz") or "")
        if not plz:
            km = eintrag.get("entfernung_km")
            self.ohne_plz.append(
                f"{eintrag.get('titel', '')[:50]} · {eintrag.get('ort') or '?'}"
                + (f" · {km} km" if km is not None else ""))
            return False
        if plz.startswith(self.praefixe):
            return True
        self.verworfen += 1
        return False


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

    def suche(self, begriff: str) -> list[dict[str, Any]]:
        params = {
            "was": begriff,
            "wo": self.wo,
            "umkreis": self.umkreis,
            "angebotsart": 1,          # 1 = Arbeit (nicht Ausbildung/Praktikum)
            "veroeffentlichtseit": min(self.veroeffentlicht_seit, 100),
            "page": 1,
            "size": self.size,
            "pav": "false",            # keine Personalvermittler
        }
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


def scanne(cfg: dict[str, Any], zustand: dict[str, Any],
           nur_offline: bool = False) -> dict[str, Any]:
    screener = Screener(cfg.get("screening", {}))
    ausschluss = Ausschluss(cfg.get("ausschluss_titel"))
    umkreis = Umkreis(cfg)
    bekannt: dict[str, Any] = zustand.get("stellen", {})
    lauf_zeit = today().strftime("%Y-%m-%dT%H:%M:%SZ")
    gefunden: dict[str, dict[str, Any]] = {}

    if nur_offline:
        # Nur neu rendern: Bestand unverändert lassen, keinen Lauf protokollieren.
        return zustand

    if not nur_offline:
        session = requests.Session()
        ba = BundesagenturQuelle(cfg, session)
        rss = RssQuelle(session, float(cfg["lauf"].get("pause_sekunden", 0.6)))

        for archetyp in cfg.get("archetypen", []):
            log(f"» {archetyp['label']}")
            for begriff in archetyp.get("begriffe", []):
                treffer = ba.suche(begriff)
                log(f"  · '{begriff}': {len(treffer)}")
                for roh in treffer:
                    eintrag = BundesagenturQuelle.normalisiere(
                        roh, archetyp["id"], begriff)
                    if not eintrag or eintrag["id"] in gefunden:
                        continue
                    if ausschluss.greift(eintrag["titel"]):
                        continue
                    # Die BA hat per umkreis vorgefiltert, aber 60 km Luftlinie
                    # sind bis Bonn und Koeln — deutlich mehr als eine Stunde
                    # Fahrt. Dieselbe PLZ-Regel wie bei RSS zieht das gerade.
                    if not umkreis.drin(eintrag):
                        continue
                    gefunden[eintrag["id"]] = eintrag

        # Jede Abfrage gescheitert heisst: die Quelle ist weg, nicht der
        # Arbeitsmarkt. Abbrechen, bevor der Merge alles als entfernt markiert.
        if ba.versuche and ba.fehler == ba.versuche:
            raise QuellenAusfall(
                f"Alle {ba.versuche} BA-Abfragen fehlgeschlagen. Entweder ist "
                f"der Endpunkt erneut umgezogen ({BA_SEARCH}) oder diese "
                f"IP wird abgewiesen — GitHub-Runner laufen in Azure-"
                f"Rechenzentren, die von Behoerden-APIs oft gesperrt sind.")

        for quelle in cfg.get("rss_quellen", []):
            log(f"» RSS: {quelle['label']}")
            roh_eintraege = rss.hole(quelle)
            for eintrag in roh_eintraege:
                if eintrag["id"] in gefunden:
                    continue
                if ausschluss.greift(eintrag["titel"]):
                    continue
                # Die Feeds liefern bundesweit — hier faellt alles ausserhalb
                # des Pendelradius raus.
                if not umkreis.drin(eintrag):
                    continue
                gefunden[eintrag["id"]] = eintrag
            log(f"  · {len(roh_eintraege)} im Feed")

        if rss.versuche and rss.fehler == rss.versuche:
            raise QuellenAusfall(
                f"Alle {rss.versuche} RSS-Feeds fehlgeschlagen. Feed-URLs in "
                f"config.yaml pruefen oder service.bund.de ist gerade weg.")

        from jobradar.seiten import SeitenQuelle
        seiten = SeitenQuelle(session, float(cfg["lauf"].get("pause_sekunden", 0.6)))
        for quelle in cfg.get("seiten_quellen", []):
            treffer = seiten.hole(quelle)
            log(f"» Seite: {quelle['label']}: {len(treffer)}")
            for eintrag in treffer:
                if eintrag["id"] in gefunden:
                    continue
                if ausschluss.greift(eintrag["titel"]):
                    continue
                gefunden[eintrag["id"]] = eintrag
        for hinweis in seiten.uebersprungen:
            log(f"  ! übersprungen — {hinweis}")

        log(f"» {ausschluss.gezaehlt} Anzeigen per Titelfilter ausgeschlossen")
        log(f"» {umkreis.verworfen} ausserhalb des Umkreises verworfen")
        if umkreis.ohne_plz:
            log(f"» {len(umkreis.ohne_plz)} ohne PLZ verworfen — pruefen, ob "
                f"eine davon doch in Reichweite liegt:")
            for hinweis in umkreis.ohne_plz:
                log(f"    – {hinweis}")

        # Volltexte nur für wirklich neue Anzeigen holen – spart Requests.
        neu = [e for e in gefunden.values()
               if e["id"] not in bekannt and "_volltext" not in e]
        log(f"» Volltext für {len(neu)} neue Anzeigen")
        for eintrag in neu:
            eintrag["_volltext"] = ba.details(eintrag["refnr"]) if eintrag["refnr"] else ""
            eintrag["_volltext_echt"] = bool(eintrag["_volltext"])

    # Zusammenführen: Neues screenen, Bekanntes behalten.
    stellen: dict[str, Any] = {}
    for eid, eintrag in gefunden.items():
        if eid in bekannt:
            alt = bekannt[eid]
            alt["zuletzt_gesehen"] = lauf_zeit
            alt["neu"] = False
            stellen[eid] = alt
            continue
        volltext = eintrag.pop("_volltext", "") or eintrag["titel"]
        strukturiert = eintrag.pop("_strukturiert", None)
        echt = eintrag.pop("_volltext_echt", None)
        eintrag["screening"] = screener.run(volltext, eintrag.get("vertragsdauer"))
        # Ob wirklich ein Anzeigentext geprueft wurde, meldet die Quelle selbst.
        # Frueher entschied das eine Laengenschwelle (< 200 Zeichen) — die hat
        # RSS-Eintraege faktisch nach Titellaenge sortiert und bei langen Titeln
        # ein sauberes Screening vorgetaeuscht, obwohl nie ein Anzeigentext
        # vorlag. Ohne Angabe der Quelle bleibt die Schwelle als Notbehelf.
        if echt is None:
            echt = strukturiert is not False and len(volltext) >= 200
        eintrag["screening"]["nur_titel"] = not echt
        eintrag["erstmals_gesehen"] = lauf_zeit
        eintrag["zuletzt_gesehen"] = lauf_zeit
        eintrag["neu"] = True
        eintrag["gesichtet"] = False
        stellen[eid] = eintrag

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

    laeufe = zustand.get("laeufe", [])[-29:]
    laeufe.append({
        "zeit": lauf_zeit,
        "gefunden": len(gefunden),
        "neu": sum(1 for s in stellen.values() if s.get("neu")),
        "gesamt": len(stellen),
        "ausgeschlossen": ausschluss.gezaehlt,
        "ausserhalb_umkreis": umkreis.verworfen,
        "ohne_plz": len(umkreis.ohne_plz),
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
