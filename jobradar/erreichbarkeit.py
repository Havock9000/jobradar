"""Arbeitsmodell, Fahrzeit und Wochenbudget.

Luftlinie ist als Pendelmass unbrauchbar: 60 km Luftlinie reichen von Hamm
(Sieg) bis Bonn und Koeln, real ist das eine Stunde und mehr. Gerechnet wird
deshalb in Fahrminuten.

Ohne ORS_API_KEY wird geschaetzt — aber jede geschaetzte Zeit ist als solche
gekennzeichnet und im Dashboard sichtbar. Ein stiller Fallback waere hier
besonders schaedlich, weil die Fahrzeit ueber Aufnahme oder Ausschluss
entscheidet.

ORS liefert reine PKW-Fahrzeit. Bei guter Bahnanbindung weicht der
Tuer-zu-Tuer-Wert davon ab; das steht auch im Fuss des Dashboards.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

ORS_GEOCODE = "https://api.openrouteservice.org/geocode/search"
ORS_ROUTE = "https://api.openrouteservice.org/v2/directions/{profil}"

WORTZAHL = {"ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4,
            "fünf": 5, "fuenf": 5}


class Arbeitsmodell:
    """Klassifiziert remote / hybrid / onsite / unklar aus dem Anzeigentext.

    Abgrenzung, die leicht falsch laeuft: "Homeoffice moeglich" und "anteilig
    mobil" sind HYBRID, nicht remote. Nur eine ausdrueckliche Anteilsangabe ab
    90 % oder eine Formulierung wie "vollstaendig remote" zaehlt als remote.
    """

    # Eine echte Anzeige schreibt "(KEIN 100 % Homeoffice/Remote)". Ohne diese
    # Pruefung liest das Muster daraus das genaue Gegenteil heraus.
    VERNEINUNG = re.compile(r"\b(kein\w*|nicht|ohne|statt)\b[^.;!?]{0,40}$",
                            re.IGNORECASE)

    def __init__(self, cfg: dict[str, Any]):
        e = cfg.get("erreichbarkeit") or {}
        muster = e.get("arbeitsmodell") or {}
        self.remote = [re.compile(m, re.IGNORECASE)
                       for m in muster.get("remote") or []]
        self.onsite = [re.compile(m, re.IGNORECASE)
                       for m in muster.get("onsite") or []]
        self.hybrid = [re.compile(m, re.IGNORECASE)
                       for m in muster.get("hybrid") or []]
        self.tage = [re.compile(m, re.IGNORECASE)
                     for m in e.get("praesenztage") or []]

    def _treffer(self, muster: list, text: str):
        for pat in muster:
            for m in pat.finditer(text):
                davor = text[max(0, m.start() - 60):m.start()]
                if self.VERNEINUNG.search(davor):
                    continue
                return m
        return None

    def bestimme(self, text: str | None) -> dict[str, Any]:
        text = text or ""
        if not text.strip():
            return {"modell": "unklar", "beleg": None, "praesenztage": None}

        # Reihenfolge: remote schlaegt alles, danach ausdrueckliche
        # Praesenzpflicht, erst dann die weichen Hybrid-Formulierungen.
        for name, muster in (("remote", self.remote),
                             ("onsite", self.onsite),
                             ("hybrid", self.hybrid)):
            m = self._treffer(muster, text)
            if m:
                start = max(0, m.start() - 55)
                ende = min(len(text), m.end() + 55)
                beleg = "…" + text[start:ende].strip() + "…"
                return {"modell": name, "beleg": beleg,
                        "praesenztage": self.praesenztage(text)}
        return {"modell": "unklar", "beleg": None,
                "praesenztage": self.praesenztage(text)}

    def praesenztage(self, text: str) -> int | None:
        for pat in self.tage:
            m = pat.search(text or "")
            if not m:
                continue
            roh = m.group(1).lower()
            if roh.isdigit():
                return int(roh)
            if roh in WORTZAHL:
                return WORTZAHL[roh]
        return None


class Fahrzeit:
    """Fahrzeit in Minuten, mit Cache und ausgewiesener Schaetzung."""

    def __init__(self, cfg: dict[str, Any], wurzel: Path, session: Any = None):
        e = cfg.get("erreichbarkeit") or {}
        self.ors = e.get("ors") or {}
        self.schaetzung = e.get("schaetzung") or {}
        self.profil = self.ors.get("profil", "driving-car")
        standort = cfg.get("standort") or {}
        self.praefixe = tuple(str(p) for p in standort.get("plz_praefixe") or [])
        self.key = os.environ.get("ORS_API_KEY") or ""
        self.session = session
        self.pfad = wurzel / self.ors.get("cache", "data/fahrzeiten.json")
        self.cache: dict[str, Any] = {}
        if self.pfad.exists():
            try:
                self.cache = json.loads(self.pfad.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.cache = {}
        self.api_aufrufe = 0
        self.anker = standort.get("ort") or standort.get("wo") or ""

    def _schluessel(self, eintrag: dict[str, Any]) -> str:
        ort = (eintrag.get("ort") or "").strip().lower()
        return str(eintrag.get("plz") or "") + "|" + ort

    def sichern(self) -> None:
        try:
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
            self.pfad.write_text(
                json.dumps(self.cache, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError:
            pass

    def _geocode(self, text: str):
        self.api_aufrufe += 1
        r = self.session.get(ORS_GEOCODE, timeout=25, params={
            "api_key": self.key, "text": text,
            "boundary.country": "DE", "size": 1})
        r.raise_for_status()
        return r.json()["features"][0]["geometry"]["coordinates"]

    def _ors(self, ort: str, plz: str) -> int | None:
        if not self.key or self.session is None:
            return None
        ziel = (plz + " " + ort).strip()
        if not ziel:
            return None
        try:
            koord = self._geocode(ziel)
            start = self._geocode(self.anker)
            self.api_aufrufe += 1
            r = self.session.post(
                ORS_ROUTE.format(profil=self.profil),
                headers={"Authorization": self.key,
                         "Content-Type": "application/json"},
                json={"coordinates": [start, koord]}, timeout=30)
            r.raise_for_status()
            sekunden = r.json()["routes"][0]["summary"]["duration"]
            return int(round(sekunden / 60.0))
        except Exception:
            # Jeder Fehler faellt auf die Schaetzung zurueck. Ein Ausfall von
            # ORS darf den Lauf nicht beenden — die Schaetzung ist als solche
            # gekennzeichnet, es entsteht also kein falscher Eindruck.
            return None

    def fuer(self, eintrag: dict[str, Any]) -> dict[str, Any]:
        schluessel = self._schluessel(eintrag)
        gecacht = self.cache.get(schluessel)
        if gecacht is not None:
            # Ein geschaetzter Wert darf nicht ewig stehenbleiben, nur weil er
            # einmal im Cache gelandet ist: Sobald ein ORS_API_KEY vorliegt,
            # wird er einmalig durch die echte Fahrzeit ersetzt. Andernfalls
            # haette das Setzen des Keys keinerlei Wirkung auf den Bestand.
            if not (gecacht.get("geschaetzt") and self.key):
                return dict(gecacht)
        ergebnis = self._ermittle(eintrag)
        if schluessel.strip("|"):
            self.cache[schluessel] = ergebnis
        return dict(ergebnis)

    def _ermittle(self, eintrag: dict[str, Any]) -> dict[str, Any]:
        ort = eintrag.get("ort") or ""
        plz = str(eintrag.get("plz") or "")

        minuten = self._ors(ort, plz)
        if minuten is not None:
            return {"minuten": minuten, "geschaetzt": False, "quelle": "ORS"}

        km = eintrag.get("entfernung_km")
        if km is not None:
            faktor = float(self.schaetzung.get("umweg_faktor", 1.35))
            kmh = float(self.schaetzung.get("schnitt_kmh", 65))
            minuten = int(math.ceil(float(km) * faktor / kmh * 60))
            return {"minuten": minuten, "geschaetzt": True,
                    "quelle": "Luftlinie"}

        if plz and self.praefixe:
            nah = plz.startswith(self.praefixe)
            wert = self.schaetzung.get(
                "plz_treffer_min" if nah else "plz_fehltreffer_min")
            return {"minuten": int(wert), "geschaetzt": True,
                    "quelle": "PLZ-Raster"}

        # Quellen ohne PLZ (JobSpy nennt nur "Bonn, NW, DE") koennen ueber den
        # Ortsnamen an einen bereits bekannten Wert anknuepfen. Die Bundesagentur
        # liefert PLZ und Ort, damit steht fuer die meisten Staedte der Region
        # schon eine Zeit im Cache.
        if ort:
            for schluessel, wert in self.cache.items():
                if schluessel.split("|", 1)[-1] == ort.strip().lower():
                    return {"minuten": wert.get("minuten"), "geschaetzt": True,
                            "quelle": "Ortsname aus Cache"}

        return {"minuten": None, "geschaetzt": True, "quelle": "unbekannt"}


class Regelwerk:
    """Entscheidet, ob eine Stelle nach Fahrzeit und Wochenbudget erreichbar ist."""

    def __init__(self, cfg: dict[str, Any]):
        e = cfg.get("erreichbarkeit") or {}
        self.budget = int(e.get("wochenbudget_min", 450))
        self.schwellen = {
            "remote": (e.get("remote") or {}).get("max_fahrzeit_min"),
            "hybrid": (e.get("hybrid") or {}).get("max_fahrzeit_min"),
            "onsite": (e.get("onsite") or {}).get("max_fahrzeit_min"),
        }
        unklar = e.get("unklar") or {}
        # Eine eigene Schwelle fuer `unklar` schlaegt das Ausweichen auf ein
        # anderes Modell. Ohne sie waere "unbekannt" so grosszuegig behandelt
        # wie "hybrid nachgewiesen" — und "unbekannt" ist hier der Normalfall.
        self.schwellen["unklar"] = unklar.get("max_fahrzeit_min")
        self.unklar_als = unklar.get("behandeln_als") or "hybrid"

    def pruefe(self, modell: str, minuten: int | None,
               praesenztage: int | None) -> dict[str, Any]:
        # `unklar` wird NICHT gefiltert, sondern gegen die Hybrid-Schwelle
        # geprueft. Forschungseinrichtungen und Verwaltungen nennen das Modell
        # selten; ein harter Ausschluss killt genau die interessanten Stellen.
        if modell == "unklar" and self.schwellen.get("unklar") is not None:
            effektiv, schwelle = "unklar", self.schwellen["unklar"]
        else:
            effektiv = self.unklar_als if modell == "unklar" else modell
            schwelle = self.schwellen.get(effektiv)

        if minuten is None:
            return {"erlaubt": True, "grund": None,
                    "hinweis": "Fahrzeit nicht ermittelbar"}
        if schwelle is None:
            return {"erlaubt": True, "grund": None, "hinweis": None}
        if minuten > int(schwelle):
            hinweis = (str(minuten) + " min > " + str(schwelle)
                       + " min (" + effektiv + ")")
            return {"erlaubt": False, "grund": "fahrzeit", "hinweis": hinweis}
        if praesenztage:
            woche = praesenztage * minuten * 2
            if woche > self.budget:
                hinweis = (str(praesenztage) + " Präsenztage × " + str(minuten)
                           + " min × 2 = " + str(woche) + " min > "
                           + str(self.budget) + " min")
                return {"erlaubt": False, "grund": "wochenbudget",
                        "hinweis": hinweis}
        return {"erlaubt": True, "grund": None, "hinweis": None}
