"""Optionale Quelle über python-jobspy (Indeed, LinkedIn, …).

STANDARDMÄSSIG AUS. Zwei Gründe, beide nüchtern:

  * Die Nutzungsbedingungen der Portale untersagen automatisierten Zugriff.
    Das Einschalten ist eine Entscheidung des Betreibers, keine Voreinstellung.
  * LinkedIn blockt Rechenzentrums-IPs zuverlässig. Auf GitHub Actions
    (Azure) bleibt der LinkedIn-Teil ohne Wohn-Proxy leer — das ist erwartet
    und kein Fehler.

Der Import von `jobspy` passiert erst im Methodenkörper. Ein fehlendes Paket
darf den Lauf nicht abbrechen, sondern nur diese eine Quelle stillegen.
"""

from __future__ import annotations

import math
import os
from typing import Any, Callable

# 1 Meile = 1,609344 km. JobSpy erwartet Meilen, die Konfiguration steht in km.
KM_JE_MEILE = 1.609344


def _proxies() -> list[str] | None:
    roh = (os.environ.get("JOBSPY_PROXIES") or "").strip()
    if not roh:
        return None
    liste = [p.strip() for p in roh.split(",") if p.strip()]
    return liste or None


class JobSpyQuelle:
    """Gleiche Signatur wie BundesagenturQuelle: `suche(begriff)` gibt Rohdaten,
    `normalisiere(roh, archetyp, begriff)` macht daraus einen Stelleneintrag."""

    def __init__(self, cfg: dict[str, Any], log: Callable[[str], None]):
        js = cfg.get("jobspy") or {}
        self.aktiv = bool(js.get("aktiv"))
        self.sites = list(js.get("sites") or ["indeed"])
        self.results_wanted = int(js.get("results_wanted", 50))
        self.hours_old = int(js.get("hours_old", 168))
        self.linkedin_beschreibung = bool(js.get("linkedin_beschreibung_laden"))
        standort = cfg.get("standort") or {}
        # PLZ vor Ortsname: Gemessen am 01.09.2026 geocodiert Indeed
        # "Hamm (Sieg)" auf ein anderes Hamm und liefert Treffer aus
        # Gerolstein, Wittlich und Birkenfeld — Eifel statt Westerwald.
        # Mit "57577" kommen Bonn, Köln, Koblenz, Herborn, also die Region.
        self.ort = standort.get("wo") or standort.get("ort") or ""
        km = float(standort.get("umkreis_km", 60))
        # Aufrunden: lieber etwas zu weit suchen, die Fahrzeitprüfung zieht
        # die eigentliche Grenze.
        self.distance = int(math.ceil(km / KM_JE_MEILE))
        self.log = log
        self.versuche = 0
        self.fehler = 0

    def suche(self, begriff: str) -> list[dict[str, Any]]:
        if not self.aktiv:
            return []
        try:
            from jobspy import scrape_jobs  # lazy: fehlendes Paket ist kein Abbruch
        except ImportError:
            self.log("  ! jobspy nicht installiert — Quelle übersprungen "
                     "(pip install -r requirements.txt)")
            self.aktiv = False
            return []

        self.versuche += 1
        try:
            df = scrape_jobs(
                site_name=self.sites,
                search_term=begriff,
                location=self.ort,
                distance=self.distance,
                country_indeed="Germany",
                results_wanted=self.results_wanted,
                hours_old=self.hours_old,
                description_format="markdown",
                linkedin_fetch_description=self.linkedin_beschreibung,
                proxies=_proxies(),
            )
        except Exception as exc:
            # Ein 429 von LinkedIn darf den Gesamtlauf nicht beenden.
            self.fehler += 1
            self.log(f"  ! JobSpy '{begriff}' fehlgeschlagen: "
                     f"{type(exc).__name__}: {exc}")
            return []

        if df is None or len(df) == 0:
            return []
        return [
            {k: (None if _ist_leer(v) else v) for k, v in zeile.items()}
            for zeile in df.to_dict("records")
        ]

    @staticmethod
    def normalisiere(roh: dict[str, Any], archetyp: str,
                     begriff: str) -> dict[str, Any] | None:
        url = roh.get("job_url") or roh.get("job_url_direct")
        if not url:
            return None
        beschreibung = (roh.get("description") or "").strip()
        ort = _stadt(roh)
        return {
            # Der Board-Name, nicht "jobspy" — im Dashboard soll stehen, wo es
            # tatsächlich herkommt.
            "id": f"js:{url}",
            "refnr": None,
            "quelle": str(roh.get("site") or "jobspy"),
            "titel": (roh.get("title") or "").strip(),
            "arbeitgeber": (roh.get("company") or "").strip(),
            "ort": ort,
            "plz": "",
            "entfernung_km": None,
            "veroeffentlicht": _datum(roh.get("date_posted")),
            "frist": None,
            "eintritt": None,
            "url": url,
            "archetyp": archetyp,
            "treffer_begriff": begriff,
            "vertragsdauer": None,
            "quereinstieg": None,
            "_volltext": beschreibung,
            # KRITISCH: Ohne Beschreibung laufen Screening und Scoring ins
            # Leere und die Stelle sähe unauffällig aus. Sie wird deshalb als
            # `unbekannt` geführt und bekommt keinen Score.
            "_volltext_echt": bool(beschreibung),
        }


def _stadt(roh: dict[str, Any]) -> str:
    """Nur der Stadtname, ohne Bundesland und Land.

    JobSpy liefert (Stand 1.1.82) keine `city`-Spalte, sondern `location` als
    "Leverkusen, NW, DE". Der Fahrzeit-Cache ist nach reinen Ortsnamen
    aufgebaut — mit dem vollen String findet er nichts, und jede Anzeige
    bliebe ohne bestimmbare Fahrzeit.
    """
    stadt = roh.get("city")
    if stadt and stadt == stadt:            # NaN-Pruefung ohne pandas
        return str(stadt).strip()
    ort = str(roh.get("location") or "").strip()
    return ort.split(",")[0].strip() if ort else ""


def _ist_leer(wert: Any) -> bool:
    if wert is None:
        return True
    # pandas liefert NaN für fehlende Werte; ohne Import von pandas prüfen.
    return wert != wert


def _datum(wert: Any) -> str | None:
    if not wert:
        return None
    text = str(wert)[:10]
    return text if len(text) == 10 and text[4] == "-" else None
