"""Deduplizierung ueber Quellenrgenzen hinweg.

Dieselbe Stelle taucht regelmaessig mehrfach auf: die Bundesagentur bekommt sie
vom Arbeitgeber, service.bund.de importiert sie aus Interamt, und bei
eingeschaltetem JobSpy steht sie zusaetzlich auf Indeed. Ohne Zusammenfuehrung
liest man dieselbe Anzeige dreimal.

Zwei Stufen:
  1. Exakter Schluessel aus normalisiertem Arbeitgeber + Ort + Titel.
  2. Innerhalb gleicher Arbeitgeber+Ort-Gruppe ein unscharfer Titelvergleich,
     weil Portale Titel unterschiedlich kuerzen.

Bewusst ohne neue Abhaengigkeit: difflib steht in der Standardbibliothek.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# (m/w/d), (w/m/d), (m/w/d/o), (f/m/d), (gn), (d/m/w) ...
GESCHLECHT = re.compile(r"\(\s*(?:[mwdfxaogn][\s/|,.]*){2,}\)", re.IGNORECASE)
KLAMMER = re.compile(r"\([^)]{0,60}\)")
# ACHTUNG: "in(?:nen)?" — nicht "innen?". Letzteres liest sich als
# "inne" plus optionales "n" und laesst "*in" stehen.
GENDERSUFFIX = re.compile(r"[*:_/]-?in(?:nen)?\b", re.IGNORECASE)
NICHTWORT = re.compile(r"[^\w\s]", re.UNICODE)
LEERRAUM = re.compile(r"\s+")


def normalisiere(text: str | None) -> str:
    """Macht Schreibvarianten desselben Titels vergleichbar.

    "Referent*in Öffentlichkeitsarbeit (m/w/d)" und
    "Referent/-in Oeffentlichkeitsarbeit" sollen denselben Schluessel ergeben.
    """
    t = (text or "").lower()
    t = GESCHLECHT.sub(" ", t)
    t = GENDERSUFFIX.sub("", t)
    t = KLAMMER.sub(" ", t)
    t = NICHTWORT.sub(" ", t)
    return LEERRAUM.sub(" ", t).strip()


def _beschreibungslaenge(eintrag: dict[str, Any]) -> int:
    text = eintrag.get("_volltext")
    if text is None:
        text = (eintrag.get("screening") or {}).get("textlaenge") or 0
        return int(text)
    return len(text or "")


def _ist_bundesagentur(eintrag: dict[str, Any]) -> bool:
    return str(eintrag.get("id", "")).startswith("ba:")


def _besser(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Gewinnt a gegen b? Laengere Beschreibung schlaegt, bei Gleichstand die
    Bundesagentur — deren refnr ist stabil, danach laesst sich die Anzeige
    spaeter wiederfinden."""
    la, lb = _beschreibungslaenge(a), _beschreibungslaenge(b)
    if la != lb:
        return la > lb
    return _ist_bundesagentur(a) and not _ist_bundesagentur(b)


def _uebernimm_verweis(gewinner: dict[str, Any], verlierer: dict[str, Any]) -> None:
    """Nichts wird still geloescht: der Gewinner traegt, wo es sonst noch stand."""
    verweise = gewinner.setdefault("auch_gefunden_bei", [])
    eintrag = {
        "quelle": verlierer.get("quelle", ""),
        "url": verlierer.get("url", ""),
        "titel": verlierer.get("titel", ""),
    }
    if eintrag not in verweise and eintrag["url"] != gewinner.get("url"):
        verweise.append(eintrag)
    # Verweise des Verlierers nicht verlieren.
    for v in verlierer.get("auch_gefunden_bei", []):
        if v not in verweise:
            verweise.append(v)


def zusammenfuehren(eintraege: list[dict[str, Any]],
                    schwelle: float = 0.82) -> tuple[list[dict[str, Any]], int]:
    """Fuehrt Duplikate zusammen. Gibt (Liste, Zahl der zusammengefuehrten) zurueck.

    `schwelle` ist die Titelaehnlichkeit ab der zwei Anzeigen desselben
    Arbeitgebers am selben Ort als dieselbe Stelle gelten.
    """
    exakt: dict[tuple[str, str, str], dict[str, Any]] = {}
    zusammengefuehrt = 0

    for eintrag in eintraege:
        schluessel = (normalisiere(eintrag.get("arbeitgeber")),
                      normalisiere(eintrag.get("ort")),
                      normalisiere(eintrag.get("titel")))
        vorhanden = exakt.get(schluessel)
        if vorhanden is None:
            exakt[schluessel] = eintrag
            continue
        zusammengefuehrt += 1
        if _besser(eintrag, vorhanden):
            _uebernimm_verweis(eintrag, vorhanden)
            exakt[schluessel] = eintrag
        else:
            _uebernimm_verweis(vorhanden, eintrag)

    # Zweite Stufe: unscharf, aber nur innerhalb desselben Arbeitgebers am
    # selben Ort. Ohne diese Einschraenkung legt der Titelvergleich Stellen
    # verschiedener Arbeitgeber zusammen.
    gruppen: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = {}
    for (ag, ort, titel), eintrag in exakt.items():
        gruppen.setdefault((ag, ort), []).append((titel, eintrag))

    ergebnis: list[dict[str, Any]] = []
    for (ag, ort), gruppe in gruppen.items():
        # Ohne Arbeitgeberangabe ist die Gruppe bedeutungslos — dann waeren
        # alle Eintraege ohne Arbeitgeber eine einzige Gruppe.
        if not ag or len(gruppe) == 1:
            ergebnis.extend(e for _, e in gruppe)
            continue
        behalten: list[tuple[str, dict[str, Any]]] = []
        for titel, eintrag in gruppe:
            treffer = None
            for i, (btitel, beintrag) in enumerate(behalten):
                if SequenceMatcher(None, titel, btitel).ratio() >= schwelle:
                    treffer = i
                    break
            if treffer is None:
                behalten.append((titel, eintrag))
                continue
            zusammengefuehrt += 1
            btitel, beintrag = behalten[treffer]
            if _besser(eintrag, beintrag):
                _uebernimm_verweis(eintrag, beintrag)
                behalten[treffer] = (titel, eintrag)
            else:
                _uebernimm_verweis(beintrag, eintrag)
        ergebnis.extend(e for _, e in behalten)

    return ergebnis, zusammengefuehrt
