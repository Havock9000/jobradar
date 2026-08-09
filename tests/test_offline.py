"""Offline-Testlauf: simuliert API-Antworten und prüft Screening + Rendering.

Aufruf:  python tests/test_offline.py
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Zeitmarke, um am Ende zu pruefen, dass der Test den echten Bestand in Ruhe
# gelassen hat. Eine Sekunde Puffer wegen grober Dateisystem-Aufloesung.
start_zeit = time.time() - 1

import yaml  # noqa: E402

from jobradar.render import baue_dashboard  # noqa: E402
from jobradar.scan import (  # noqa: E402
    Ausschluss, BundesagenturQuelle, RssQuelle, Screener, Umkreis, parse_date,
)

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

# --- 0. Titel-Ausschluss: raus muss raus, drin muss drin bleiben -----------
ausschluss = Ausschluss(cfg["ausschluss_titel"])

raus = [
    "Performance Marketing Manager (m/w/d)",
    "Social Media Manager (m/w/d)",
    "SEO-Redakteur (m/w/d)",
    "Junior Social-Media-Redakteur",
    "Vertriebsmitarbeiter im Außendienst (m/w/d)",
    "Community Manager Gaming",
    "E-Commerce Content Specialist",
    "Außendienstmitarbeiter (m/w/d) für die Region Mitte",
]
drin = [
    "Mediengestalter Bild und Ton (m/w/d)",
    "Videoredakteur*in für Langformate",
    "Referent*in Presse- und Öffentlichkeitsarbeit (inkl. Social Media)",
    "Mitarbeiter*in Wirtschaftsförderung",
    "Medienpädagoge*in Kreismedienzentrum",
    "Sachbearbeitung Kulturamt (m/w/d)",
    "Kameramann/-frau Dokumentation",
    # Echter Feed-Titel vom 2026-08-09: kommunaler Außendienst ist kein
    # Vertrieb. Fiel vorher dem Muster /Außendienst/ zum Opfer.
    "Sachbearbeitung Ordnungswidrigkeiten/Außendienst innerhalb der Abteilung",
]

print("Titelfilter:")
for titel in raus:
    treffer = ausschluss.greift(titel)
    print(f"  [{'ok ' if treffer else 'FEHLER'}] raus: {titel}")
    assert treffer, f"haette ausgeschlossen werden muessen: {titel}"
for titel in drin:
    treffer = ausschluss.greift(titel)
    print(f"  [{'ok ' if not treffer else 'FEHLER'}] drin: {titel}"
          + (f"  <- faelschlich gekillt von /{treffer}/" if treffer else ""))
    assert not treffer, f"faelschlich ausgeschlossen: {titel} durch /{treffer}/"

# --- 1. Screening gegen echte Formulierungen aus Ausschreibungen ------------
screener = Screener(cfg["screening"])

faelle = [
    ("Eine abgeschlossene Berufsausbildung bzw. ein abgeschlossenes Studium oder "
     "eine vergleichbare Ausbildung/Erfahrung im Bereich Kommunikation. Erfahrungen "
     "in der Verbandsarbeit oder Zusammenarbeit mit Ehrenamtlichen. Unbefristet.",
     "weich", True, False),
    ("Vorausgesetzt wird ein abgeschlossenes wissenschaftliches Hochschulstudium "
     "der Kommunikationswissenschaft. Die Stelle ist unbefristet.",
     "hart", False, False),
    ("Erfolgreich abgeschlossene Ausbildung zum/r Mediengestalter/in Bild und Ton. "
     "Die Stelle ist zunächst für zwei Jahre befristet.",
     "offen", False, True),
]

print("Screening:")
for text, erwartet_stufe, erwartet_ehrenamt, erwartet_befristet in faelle:
    r = screener.run(text)
    stufe = r["studium"]["stufe"]
    ehrenamt = r["ehrenamtslogik"]["getroffen"]
    befristet = r["befristung"]["getroffen"]
    ok = (stufe == erwartet_stufe and ehrenamt == erwartet_ehrenamt
          and befristet == erwartet_befristet)
    print(f"  [{'ok ' if ok else 'FEHLER'}] studium={stufe} ehrenamt={ehrenamt} "
          f"befristet={befristet}")
    assert ok, f"erwartet {erwartet_stufe}/{erwartet_ehrenamt}/{erwartet_befristet}"

# --- 2. Datumsnormalisierung ----------------------------------------------
print("Datum:")
for roh, erwartet in [("2026-08-05", "2026-08-05"),
                      ("05.08.2026", "2026-08-05"),
                      ("Wed, 05 Aug 2026 09:12:00 +0200", "2026-08-05"),
                      (None, None)]:
    got = parse_date(roh)
    print(f"  [{'ok ' if got == erwartet else 'FEHLER'}] {roh!r} -> {got}")
    assert got == erwartet

# --- 3. Normalisierung einer BA-Antwort -----------------------------------
# Schema v6, wortgleich aus einer echten Antwort vom 2026-08-09 uebernommen
# (/pc/v6/jobs?was=Öffentlichkeitsarbeit&wo=57577). Der frueher hier
# hinterlegte v4-Fixture hat den Bruch verdeckt: das Modul hat monatelang
# Feldnamen erwartet, die es nicht mehr gab, und der Test war trotzdem gruen.
echte_v6_antwort = {
    "stellenangebotsTitel": "Teilsachgebietsleiterin / Teilsachgebietsleiter Öffentlichkeitsarbeit (m/w/d)",
    "hauptberuf": "Medienwissenschaftler/in",
    "firma": "Bundesamt für das Personalmanagement der Bundeswehr  Abteilung V",
    "referenznummer": "13270-2026-00006447-1-S",
    "stellenlokationen": [
        {"adresse": {"plz": "50737", "ort": "Köln", "region": "NORDRHEIN_WESTFALEN"}}
    ],
    "entfernung": 58,
    "datumErsteVeroeffentlichung": "2026-07-30",
    "veroeffentlichungszeitraum": {"von": "2026-07-30"},
    "eintrittszeitraum": {"von": "2026-12-01"},
    "vertragsdauer": "UNBEFRISTET",
    "quereinstiegGeeignet": False,
}
echt = BundesagenturQuelle.normalisiere(echte_v6_antwort, "pressestelle",
                                        "Presse- und Öffentlichkeitsarbeit")
assert echt["id"] == "ba:13270-2026-00006447-1-S"
assert echt["titel"].startswith("Teilsachgebietsleiterin")
assert echt["arbeitgeber"].startswith("Bundesamt")
assert echt["ort"] == "Köln" and echt["plz"] == "50737"
assert echt["entfernung_km"] == 58          # steht in v6 auf oberster Ebene
assert echt["veroeffentlicht"] == "2026-07-30"
assert echt["eintritt"] == "2026-12-01"
assert echt["vertragsdauer"] == "UNBEFRISTET"
print("Normalisierung (echtes v6-Schema):")
print(f"  [ok ] {echt['titel'][:52]}… – {echt['ort']}, {echt['entfernung_km']} km")

# Strukturierte Vertragsdauer schlaegt das Regex-Muster und nennt ihre Herkunft.
r_unbefr = screener.run("Die Stelle ist befristet.", "UNBEFRISTET")
assert r_unbefr["befristung"]["getroffen"] is False
assert "strukturierte Angabe" in r_unbefr["befristung"]["beleg"]
r_befr = screener.run("Kein Hinweis im Text.", "BEFRISTET")
assert r_befr["befristung"]["getroffen"] is True
print("  [ok ] vertragsdauer schlaegt Regex, Beleg nennt die Herkunft")


def _v6(refnr, titel, firma, datum, ort, plz, km):
    return {"referenznummer": refnr, "stellenangebotsTitel": titel, "firma": firma,
            "datumErsteVeroeffentlichung": datum, "entfernung": km,
            "stellenlokationen": [{"adresse": {"ort": ort, "plz": plz}}]}


eintrag = BundesagenturQuelle.normalisiere(
    _v6("10001-1002716922-S", "Referent*in Wissenschaftskommunikation (m/w/d)",
        "Universität Siegen", "2026-08-05", "Siegen", "57076", 38),
    "wisskomm", "Wissenschaftskommunikation")
assert eintrag["entfernung_km"] == 38
assert eintrag["url"].endswith("10001-1002716922-S")

# --- 3b. RSS-Feldtrennung und Ortsfilter ----------------------------------
# Wortgleiche Zusammenfassung aus dem Feed vom 2026-08-09. Eine einzige Zeile
# ohne Trennzeichen — genau daran ist die alte Regex [^|;\n]{3,80} gescheitert.
summary = ("Arbeitgeber: Landkreis Oder-Spree Ort: 15848 Beeskow "
           "Bewerbungsfrist: 06.09.2026 00:00 Veröffentlichungsende: 07.09.2026 00:00")

print("RSS-Feldtrennung:")
ag = RssQuelle._arbeitgeber(summary, "")
ort = RssQuelle._ort(summary)
frist = RssQuelle._frist(summary)
plz = RssQuelle._plz(ort)
for label, got, erwartet in [("Arbeitgeber", ag, "Landkreis Oder-Spree"),
                             ("Ort", ort, "15848 Beeskow"),
                             ("PLZ", plz, "15848"),
                             ("Frist", frist, "2026-09-06")]:
    print(f"  [{'ok ' if got == erwartet else 'FEHLER'}] {label}: {got!r}")
    assert got == erwartet, f"{label}: {got!r} statt {erwartet!r}"

print("Ortsfilter:")
umkreis = Umkreis(cfg)
faelle_ort = [
    ("57577", True,  "Hamm/Sieg — Wohnort"),
    ("57610", True,  "Altenkirchen"),
    ("51545", True,  "Waldbröl"),
    ("15848", False, "Beeskow — 500 km weg"),
    ("31134", False, "Hildesheim"),
    ("53111", False, "Bonn — bewusst draußen"),
    ("",      False, "ohne PLZ nicht beurteilbar"),
]
for plz_test, erwartet, was in faelle_ort:
    got = umkreis.drin({"plz": plz_test})
    print(f"  [{'ok ' if got == erwartet else 'FEHLER'}] {plz_test or '(leer)':>5} "
          f"-> {'drin' if got else 'raus'}  · {was}")
    assert got == erwartet, f"{plz_test}: {got} statt {erwartet}"

# Ohne konfigurierte Praefixe darf nichts gefiltert werden.
assert Umkreis({"standort": {}}).drin({"plz": "15848"}) is True
print("  [ok ] leere Praefixliste filtert nicht")

# --- 3c. Quellenausfall darf den Bestand nicht leeren ---------------------
# Ohne diese Sicherung ist ein Totalausfall nicht von "alle Anzeigen
# zurueckgezogen" zu unterscheiden: der Merge markiert jede bekannte Stelle
# als entfernt, das Dashboard meldet einen leeren Bestand, der Lauf endet
# mit Erfolg. Auf einem GitHub-Runner (Azure-IP) ist das ein realistischer Fall.
print("Quellenausfall:")
import requests as _requests  # noqa: E402

from jobradar import scan as _scan  # noqa: E402


class _ToteSession:
    """Jede Anfrage scheitert — simuliert gesperrte oder tote Quelle."""

    def get(self, *a, **k):
        raise _requests.RequestException("Verbindung abgewiesen (simuliert)")


bestand = {"stellen": {"ba:alt-1": {"id": "ba:alt-1", "titel": "Bestandsstelle",
                                    "zuletzt_gesehen": "2026-08-08T08:00:00Z"}},
           "laeufe": []}
vorher = json.dumps(bestand, sort_keys=True)

_echte_session = _scan.requests.Session
_scan.requests.Session = _ToteSession
try:
    _scan.scanne({**cfg, "seiten_quellen": [], "rss_quellen": []}, bestand)
    raise AssertionError("QuellenAusfall wurde nicht ausgeloest")
except _scan.QuellenAusfall as exc:
    print(f"  [ok ] abgebrochen statt Bestand zu leeren")
    assert "BA-Abfragen fehlgeschlagen" in str(exc)
finally:
    _scan.requests.Session = _echte_session

assert json.dumps(bestand, sort_keys=True) == vorher, \
    "Bestand wurde trotz Ausfall veraendert"
print("  [ok ] Bestand unveraendert geblieben")

# --- 4. Dashboard aus simuliertem Zustand ---------------------------------
zustand = {"stellen": {}, "laeufe": [{"zeit": "2026-08-08T08:00:00Z",
                                     "gefunden": 4, "neu": 3, "gesamt": 4}]}

muster = [
    (eintrag, faelle[1][0], True),
    (BundesagenturQuelle.normalisiere(
        _v6("10001-9990001-S", "Mitarbeiter*in NABU-Regionalstelle Rhein-Westerwald",
            "NABU Rheinland-Pfalz", "2026-07-27", "Holler", "56412", 47),
        "naturschutz", "Öffentlichkeitsarbeit Naturschutz"), faelle[0][0], True),
    (BundesagenturQuelle.normalisiere(
        _v6("10001-9990002-S", "Videoredakteur*in Bewegtbild (m/w/d)",
            "Kreisverwaltung Altenkirchen", "2026-08-01", "Altenkirchen", "57610", 22),
        "medienproduktion", "Videoredakteur"), faelle[2][0], True),
    (BundesagenturQuelle.normalisiere(
        _v6("10001-9990003-S", "Pressesprecher*in",
            "Stadt Siegen", "2026-06-14", "Siegen", "57072", 40),
        "pressestelle", "Pressesprecher"), faelle[1][0], False),
]

fristen = {"ba:10001-9990001-S": "2026-08-21",   # laeuft bald ab
           "ba:10001-9990002-S": "2026-09-30",
           "ba:10001-9990003-S": "2026-07-01"}   # abgelaufen

for e, text, neu in muster:
    e["screening"] = screener.run(text)
    e["frist"] = fristen.get(e["id"])
    e["screening"]["nur_titel"] = e["id"].endswith("9990002-S")
    e["neu"] = neu
    e["erstmals_gesehen"] = "2026-08-08T08:00:00Z"
    e["zuletzt_gesehen"] = "2026-08-08T08:00:00Z"
    if not neu:
        e["entfernt"] = True
    zustand["stellen"][e["id"]] = e

# Der Test schrieb frueher direkt nach data/jobs.json und index.html und hat
# damit bei jedem Lauf den echten Bestand samt "neu seit letztem Lauf"-Logik
# zerstoert. Jetzt in ein Wegwerfverzeichnis.
tmp = Path(tempfile.mkdtemp(prefix="jobradar-test-"))
(tmp / "jobs.json").write_text(
    json.dumps(zustand, ensure_ascii=False, indent=2), encoding="utf-8")

ziel = baue_dashboard(cfg, zustand, tmp / "index.html")
groesse = ziel.stat().st_size
print("Dashboard:\n  [ok ] " + ziel.name + f" geschrieben, {groesse} Bytes")

for spur in (ROOT / "data" / "jobs.json", ROOT / "index.html"):
    assert not spur.exists() or spur.stat().st_mtime < start_zeit, (
        f"Test hat {spur} angefasst — das ist der echte Bestand")
print("  [ok ] echter Bestand unberuehrt")

doc = ziel.read_text(encoding="utf-8")
for pflicht in ["NABU Rheinland-Pfalz", 'data-studium="hart"', 'data-ehrenamt="1"',
                "Ehrenamtslogik ausblenden", "class=\"neu\"",
                "Abgelaufene ausblenden", 'data-abgelaufen="1"',
                "Frist abgelaufen", "nurtitel"]:
    assert pflicht in doc, f"fehlt im Dashboard: {pflicht}"
print("  [ok ] alle Pflichtelemente vorhanden")
print("\nAlles durchgelaufen.")
