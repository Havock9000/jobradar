"""Inhaltliches Scoring am Anzeigentext statt am Titel.

Der Grund fuer dieses Modul: Berufsbezeichnungen sind in diesem Feld
unzuverlaessig. Dieselbe Taetigkeit heisst je nach Arbeitgeber
"Referent*in Oeffentlichkeitsarbeit", "Sachbearbeitung Kommunikation",
"Mitarbeiter*in Stabsstelle", "Online-Redakteur*in" oder "Marketingassistenz".
Ein Titelfilter entfernt damit zwangslaeufig Passendes und behaelt Unpassendes.

Gewertet wird deshalb, welche Aufgaben im Text tatsaechlich vorkommen.

ABWEICHUNG von der Vorgabe, bewusst: Gezaehlt wird jede Aufgabengruppe
EINMAL mit ihrem Gewicht, nicht jedes Vorkommen. Sonst gewinnt die Anzeige,
die zwanzigmal "Video" schreibt, gegen die, die drei verschiedene passende
Aufgaben nennt — und genau letztere ist die bessere Stelle.
"""

from __future__ import annotations

import re
from typing import Any


def _kompiliere(gruppen: dict[str, Any]) -> dict[str, tuple[int, list]]:
    fertig: dict[str, tuple[int, list]] = {}
    for name, spec in (gruppen or {}).items():
        if not isinstance(spec, dict):
            continue
        muster = spec.get("muster") or []
        gewicht = int(spec.get("gewicht", 0))
        fertig[name] = (gewicht, [re.compile(re.escape(m) if not _ist_regex(m)
                                             else m, re.IGNORECASE)
                                  for m in muster])
    return fertig


def _ist_regex(muster: str) -> bool:
    """Die Aufgabenmuster in config.yaml sind Klartext ("Beitraege verfassen").
    Sonderzeichen darin sollen woertlich gelten, nicht als Regex-Syntax."""
    return any(z in muster for z in "[](){}|^$*+?\\")


class Passung:
    def __init__(self, cfg: dict[str, Any]):
        p = cfg.get("passung") or {}
        self.aufgaben = _kompiliere(p.get("aufgaben"))
        reibung = dict(p.get("reibung") or {})
        # titel_abwertung hat keine Muster, sondern haengt an ausschluss_titel.
        self.titel_abwertung = int(
            (reibung.pop("titel_abwertung", None) or {}).get("gewicht", 0))
        self.reibung = _kompiliere(reibung)
        self.ausschluss_titel = [re.compile(m, re.IGNORECASE)
                                 for m in cfg.get("ausschluss_titel") or []]
        # Fremde Berufe: greift gegen den TITEL. Ein Friseursalon, der
        # "Instagram" in der Anzeige nennt, trifft sonst die Aufgabengruppen
        # `social` und `bewegtbild` und steht mit +5 im Dashboard.
        fremd = p.get("fremdberuf") or {}
        self.fremdberuf_gewicht = int(fremd.get("gewicht", 0))
        self.fremdberuf = [re.compile(m, re.IGNORECASE)
                           for m in fremd.get("muster") or []]

    @staticmethod
    def _beleg(text: str, treffer: re.Match) -> str:
        start = max(0, treffer.start() - 55)
        ende = min(len(text), treffer.end() + 55)
        return "…" + text[start:ende].strip() + "…"

    def bewerte(self, titel: str, text: str | None) -> dict[str, Any]:
        """Ohne Anzeigentext gibt es KEINEN Score.

        Ein Score 0 waere hier falsch: er sieht aus wie ein Urteil, ist aber
        nur fehlende Information. Solche Stellen bekommen Status `unbekannt`
        und werden im Dashboard grau gefuehrt.
        """
        text = text or ""
        if not text.strip():
            return {"status": "unbekannt", "score": None,
                    "aufgaben": [], "reibung": []}

        score = 0
        getroffen: list[str] = []
        for name, (gewicht, muster) in self.aufgaben.items():
            if any(pat.search(text) for pat in muster):
                score += gewicht
                getroffen.append(name)

        reibung: list[dict[str, str]] = []
        for name, (gewicht, muster) in self.reibung.items():
            for pat in muster:
                m = pat.search(text)
                if m:
                    score += gewicht
                    reibung.append({"gruppe": name, "gewicht": gewicht,
                                    "beleg": self._beleg(text, m)})
                    break

        for pat in self.fremdberuf:
            m = pat.search(titel or "")
            if m:
                score += self.fremdberuf_gewicht
                reibung.append({"gruppe": "fremdberuf",
                                "gewicht": self.fremdberuf_gewicht,
                                "beleg": "Berufsbezeichnung im Titel: "
                                         + m.group(0)})
                break

        # Der alte Titelfilter lebt nur noch als Abwertung weiter.
        for pat in self.ausschluss_titel:
            m = pat.search(titel or "")
            if m:
                score += self.titel_abwertung
                reibung.append({"gruppe": "titel", "gewicht": self.titel_abwertung,
                                "beleg": "Titelmuster: " + m.group(0)})
                break

        return {"status": "bewertet", "score": score,
                "aufgaben": getroffen, "reibung": reibung}
