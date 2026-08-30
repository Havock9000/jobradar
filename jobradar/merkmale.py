"""Merkmale, die aus dem Anzeigentext gelesen werden: Umfang und Vergütung.

Beide dienen unterschiedlichen Zwecken:

  * Der Umfang ist ein HARTER Filter (unter der Mindeststundenzahl fliegt die
    Stelle raus) — aber nur, wenn eine Stundenzahl überhaupt dasteht. Eine
    fehlende Angabe schließt nicht aus.
  * Die Vergütung wird NICHT gefiltert. In der BA-Datenbank fehlt sie
    meistens, und "keine Angabe" ist kein Ausschluss. Sie wird nur angezeigt.
"""

from __future__ import annotations

import re
from typing import Any

# "20 Wochenstunden", "30 Std./Woche", "Teilzeit mit 25 Stunden",
# "Arbeitszeit: 19,5 Stunden", "39 Stunden pro Woche"
STUNDEN = [
    re.compile(r"(\d{1,2}(?:[,.]\d{1,2})?)\s*(?:Wochen-?)?[Ss]tunden?\s*"
               r"(?:/|pro\s+|je\s+)?\s*Woche", re.IGNORECASE),
    re.compile(r"(\d{1,2}(?:[,.]\d{1,2})?)\s*(?:Std\.?|h)\s*"
               r"(?:/|pro\s+|je\s+)\s*Woche", re.IGNORECASE),
    re.compile(r"(?:Wochenarbeitszeit|Arbeitszeit|Stundenumfang|Umfang)\s*"
               r"(?:von|:|beträgt)?\s*(\d{1,2}(?:[,.]\d{1,2})?)\s*"
               r"(?:Wochen-?)?[Ss]tunden?", re.IGNORECASE),
    re.compile(r"(\d{1,2}(?:[,.]\d{1,2})?)\s*Wochenstunden", re.IGNORECASE),
]

VOLLZEIT = re.compile(r"\bVollzeit\b", re.IGNORECASE)


def wochenstunden(text: str | None) -> float | None:
    """Kleinste im Text genannte Wochenstundenzahl, oder None.

    Bewusst die KLEINSTE: Anzeigen schreiben oft "Teilzeit ab 20 Stunden bis
    Vollzeit 39 Stunden". Für den Mindestumfang zählt die Untergrenze, denn
    die ist es, die angeboten wird.
    """
    text = text or ""
    werte: list[float] = []
    for pat in STUNDEN:
        for m in pat.finditer(text):
            try:
                wert = float(m.group(1).replace(",", "."))
            except ValueError:
                continue
            # 0 und absurde Werte ignorieren — meist Fehltreffer auf Zahlen
            # aus anderen Zusammenhängen.
            if 1.0 <= wert <= 60.0:
                werte.append(wert)
    if werte:
        return min(werte)
    return None


class Entgelt:
    """Liest eine Entgeltgruppe oder Gehaltsangabe, wenn eine dasteht."""

    def __init__(self, cfg: dict[str, Any]):
        v = cfg.get("verguetung") or {}
        self.muster = [re.compile(m, re.IGNORECASE) for m in v.get("muster") or []]

    def lies(self, text: str | None) -> str | None:
        text = text or ""
        for pat in self.muster:
            m = pat.search(text)
            if m:
                return m.group(0).strip()
        return None
