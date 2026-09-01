"""Die Pipeline eines Laufs, ausgelagert aus scan.py.

Reihenfolge, und warum sie so ist:

    Quellen  →  Dedupe  →  Screening  →  Erreichbarkeit  →  harte Filter
             →  Scoring  →  Merge mit Bestand

Dedupe kommt VOR dem Screening, weil Screening der teure Schritt ist — jede
Anzeige nur einmal bewerten. Die harten Filter kommen VOR dem Scoring, weil
eine unerreichbare Stelle keinen Score braucht.

Gefiltert wird ausschließlich nach drei Kriterien: Fahrzeit (inkl.
Wochenbudget), Umfang unter der Mindeststundenzahl und ein zwingend
gefordertes Studium. Alles andere ist Markierung oder Punktabzug — der alte
Titel-Ausschlussfilter wirkt nur noch als Abwertung im Score.
"""

from __future__ import annotations

import re
from typing import Any

from jobradar.merkmale import Entgelt, wochenstunden

FILTERGRUENDE = ("fahrzeit", "wochenbudget", "umfang", "studium",
                 "beschaeftigung")


def _falsche_beschaeftigung(eintrag: dict[str, Any],
                            harte: dict[str, Any]) -> bool:
    """Werkstudent, Minijob, Praktikum — am Titel und an der BA-Strukturangabe.

    Das strukturierte Feld `istGeringfuegigeBeschaeftigung` schlaegt jede
    Regex: es steht bei der Bundesagentur direkt in der Anzeige und raet nicht.
    """
    if eintrag.get("geringfuegig") is True:
        return True
    muster = harte.get("ausgeschlossene_beschaeftigung") or []
    titel = eintrag.get("titel") or ""
    return any(re.search(m, titel, re.IGNORECASE) for m in muster)


def _leerer_zaehler() -> dict[str, int]:
    return {grund: 0 for grund in FILTERGRUENDE}


def bewerte_eintrag(eintrag: dict[str, Any], volltext: str, *,
                    screener, arbeitsmodell, fahrzeit, regelwerk,
                    passung, entgelt: Entgelt, cfg: dict[str, Any],
                    zaehler: dict[str, int]) -> dict[str, Any]:
    """Screening, Erreichbarkeit, harte Filter und Scoring für eine Anzeige.

    Der Eintrag wird an Ort und Stelle ergänzt und zurückgegeben.
    """
    harte = cfg.get("harte_filter") or {}
    hat_text = bool((volltext or "").strip())

    # --- Screening (S/E/B). Muster unverändert. ---------------------------
    eintrag["screening"] = screener.run(volltext, eintrag.get("vertragsdauer"))
    eintrag["screening"]["nur_titel"] = not hat_text

    # --- Arbeitsmodell und Fahrzeit ---------------------------------------
    modell = arbeitsmodell.bestimme(volltext)
    eintrag["arbeitsmodell"] = modell
    zeit = fahrzeit.fuer(eintrag)
    eintrag["fahrzeit"] = zeit
    eintrag["erreichbar"] = regelwerk.pruefe(
        modell["modell"], zeit.get("minuten"), modell.get("praesenztage"))

    # --- Umfang und Entgelt ------------------------------------------------
    stunden = wochenstunden(volltext)
    eintrag["wochenstunden"] = stunden
    eintrag["entgelt"] = entgelt.lies(volltext)

    # --- Harte Filter, in dieser Reihenfolge -------------------------------
    grund = None
    if not eintrag["erreichbar"]["erlaubt"]:
        grund = eintrag["erreichbar"]["grund"]
    elif stunden is not None and stunden < float(
            harte.get("mindest_wochenstunden", 0)):
        grund = "umfang"
    elif _falsche_beschaeftigung(eintrag, harte):
        # Werkstudent setzt eine Immatrikulation voraus, Minijob und Praktikum
        # tragen kein Einkommen. Alle drei ausdruecklich unerwuenscht.
        grund = "beschaeftigung"
    elif (harte.get("studium_zwingend_ausschliessen")
          and eintrag["screening"]["studium"]["stufe"] == "hart"):
        # Nur "hart" — Status "weich" (Studium ODER vergleichbare
        # Qualifikation) bleibt sichtbar. Das ist genau der Fall, in dem
        # Berufserfahrung greift.
        grund = "studium"

    eintrag["gefiltert"] = grund
    if grund in zaehler:
        zaehler[grund] += 1

    # --- Scoring -----------------------------------------------------------
    # Bewusst auch für gefilterte Stellen: Nur so lässt sich im Dashboard
    # unter "ausgefilterte zeigen" beurteilen, ob ein Filter zu breit greift.
    eintrag["passung"] = passung.bewerte(eintrag.get("titel", ""), volltext)
    return eintrag


def sortierschluessel(stelle: dict[str, Any]) -> tuple:
    """Score absteigend. Stellen ohne Beschreibung (`unbekannt`) ganz nach
    hinten — sie haben keinen Score, und eine 0 wäre ein Urteil, das die
    Datenlage nicht hergibt."""
    p = stelle.get("passung") or {}
    if p.get("status") != "bewertet" or p.get("score") is None:
        return (1, 0)
    return (0, -int(p["score"]))
