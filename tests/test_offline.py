"""Offline-Testlauf: simuliert Quellenantworten und prueft die ganze Pipeline.

Laeuft ohne Netz. Aufruf:  python tests/test_offline.py

Die Reihenfolge folgt der Pipeline:
Quellen -> Dedupe -> Screening -> Erreichbarkeit -> harte Filter -> Scoring.
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

from jobradar.dedupe import normalisiere, zusammenfuehren  # noqa: E402
from jobradar.erreichbarkeit import (  # noqa: E402
    Arbeitsmodell, Fahrzeit, Regelwerk,
)
from jobradar.lauf import bewerte_eintrag, _leerer_zaehler  # noqa: E402
from jobradar.merkmale import Entgelt, wochenstunden  # noqa: E402
from jobradar.passung import Passung  # noqa: E402
from jobradar.render import baue_dashboard  # noqa: E402
from jobradar.scan import (  # noqa: E402
    Ausschluss, BundesagenturQuelle, QuellenAusfall, RssQuelle, Screener,
    parse_date,
)

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
fehler = []


def pruef(bedingung, text):
    print(f"  [{'ok ' if bedingung else 'FEHLER'}] {text}")
    if not bedingung:
        fehler.append(text)


# --- 0. Titelfilter entfernt NICHTS mehr ----------------------------------
print("Titelfilter (nur noch Abwertung):")
pruef(cfg.get("ausschluss_titel_hart") is False,
      "ausschluss_titel_hart steht auf false")

passung = Passung(cfg)
werbetext = ("Sie verantworten die Redaktion des Newsletters, verfassen "
             "Pressemitteilungen und pflegen die Website.")
mit_muster = passung.bewerte("SEO-Redakteur (m/w/d)", werbetext)
ohne_muster = passung.bewerte("Redakteur (m/w/d)", werbetext)
pruef(mit_muster["score"] < ohne_muster["score"],
      f"Titelmuster wertet ab statt zu entfernen "
      f"({mit_muster['score']} < {ohne_muster['score']})")
pruef(any(r["gruppe"] == "titel" for r in mit_muster["reibung"]),
      "Abwertung erscheint als Reibungsmarker mit Beleg")

# --- 1. Dedupe -------------------------------------------------------------
print("Dedupe:")
drei_quellen = [
    {"id": "ba:1", "titel": "Referent*in Öffentlichkeitsarbeit (m/w/d)",
     "arbeitgeber": "Kreis Altenkirchen", "ort": "Altenkirchen",
     "quelle": "Bundesagentur für Arbeit", "url": "https://ba/1",
     "_volltext": "kurz"},
    {"id": "rss:2", "titel": "Referent/-in Öffentlichkeitsarbeit",
     "arbeitgeber": "Kreis Altenkirchen", "ort": "Altenkirchen",
     "quelle": "service.bund.de", "url": "https://bund/2",
     "_volltext": "x" * 400},
    {"id": "js:3", "titel": "Referent:in Öffentlichkeitsarbeit (w/m/d)",
     "arbeitgeber": "Kreis Altenkirchen", "ort": "Altenkirchen",
     "quelle": "indeed", "url": "https://indeed/3",
     "_volltext": "mittel" * 10},
]
ergebnis, doppelt = zusammenfuehren(list(drei_quellen), 0.85)
pruef(len(ergebnis) == 1, f"drei Schreibvarianten zu einer zusammengefuehrt "
                          f"(uebrig: {len(ergebnis)})")
pruef(doppelt == 2, f"zwei Duplikate gezaehlt (gezaehlt: {doppelt})")
sieger = ergebnis[0]
pruef(sieger["id"] == "rss:2", "der Eintrag mit der laengsten Beschreibung gewinnt")
quellen = {v["quelle"] for v in sieger.get("auch_gefunden_bei", [])}
pruef(quellen == {"Bundesagentur für Arbeit", "indeed"},
      f"die verworfenen Fundstellen bleiben vermerkt ({sorted(quellen)})")

# Negativfall: echte verschiedene Stellen duerfen NICHT zusammenfallen.
zwei_echte = [
    {"id": "ba:10", "titel": "Referent Öffentlichkeitsarbeit",
     "arbeitgeber": "Uni Siegen", "ort": "Siegen", "quelle": "BA",
     "url": "https://a", "_volltext": "a" * 100},
    {"id": "ba:11", "titel": "Referent Öffentlichkeitsarbeit Schwerpunkt Video",
     "arbeitgeber": "Uni Siegen", "ort": "Siegen", "quelle": "BA",
     "url": "https://b", "_volltext": "b" * 100},
]
getrennt, _ = zusammenfuehren(list(zwei_echte),
                              float(cfg["dedupe"]["titel_aehnlichkeit"]))
pruef(len(getrennt) == 2,
      "'Schwerpunkt Video' bleibt eine eigene Stelle "
      f"(Schwelle {cfg['dedupe']['titel_aehnlichkeit']})")

# Ohne Arbeitgeberangabe darf der unscharfe Vergleich nicht gruppieren.
ohne_ag = [
    {"id": "a", "titel": "Redakteur", "arbeitgeber": "", "ort": "",
     "quelle": "x", "url": "u1", "_volltext": ""},
    {"id": "b", "titel": "Redaktion", "arbeitgeber": "", "ort": "",
     "quelle": "x", "url": "u2", "_volltext": ""},
]
pruef(len(zusammenfuehren(ohne_ag, 0.85)[0]) == 2,
      "ohne Arbeitgeber wird nicht unscharf zusammengelegt")

# --- 2. Scoring: der wichtigste Test --------------------------------------
print("Scoring:")
zieltext = (
    "Zu Ihren Aufgaben gehoert die Presse- und Oeffentlichkeitsarbeit der "
    "Wirtschaftsfoerderung: Sie verfassen Pressemitteilungen, betreuen den "
    "Newsletter, dokumentieren Veranstaltungen mit Fotos und pflegen das "
    "Bildmaterial samt Nutzungsrechten. Website pflegen gehoert dazu.")
ziel = passung.bewerte("Sachbearbeitung Wirtschaftsförderung", zieltext)
pruef(ziel["score"] >= 5,
      f"Titel taeuscht, Aufgabe passt -> Score {ziel['score']} "
      f"({', '.join(ziel['aufgaben'])})")
pruef("redaktion" in ziel["aufgaben"] and "dokumentation" in ziel["aufgaben"],
      "die tragenden Aufgabengruppen sind erkannt")

vertriebstext = ("Sie gewinnen Neukunden, betreiben Akquise und verantworten "
                 "Umsatzziele im Vertrieb.")
schwach = passung.bewerte("Kommunikationsreferent (m/w/d)", vertriebstext)
pruef(schwach["score"] < ziel["score"],
      f"passender Titel + Vertriebstext scort niedrig ({schwach['score']})")

leer = passung.bewerte("Irgendein Titel", "")
pruef(leer["status"] == "unbekannt" and leer["score"] is None,
      "ohne Beschreibung: Status unbekannt, KEIN Score 0")

# --- 3. Screening ----------------------------------------------------------
print("Screening:")
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
     "Die Stelle ist zunaechst fuer zwei Jahre befristet.",
     "offen", False, True),
]
for text, erwartet_stufe, erwartet_ehrenamt, erwartet_befristet in faelle:
    r = screener.run(text)
    ok = (r["studium"]["stufe"] == erwartet_stufe
          and r["ehrenamtslogik"]["getroffen"] == erwartet_ehrenamt
          and r["befristung"]["getroffen"] == erwartet_befristet)
    pruef(ok, f"studium={r['studium']['stufe']} "
              f"ehrenamt={r['ehrenamtslogik']['getroffen']} "
              f"befristet={r['befristung']['getroffen']}")

r_unbefr = screener.run("Die Stelle ist befristet.", "UNBEFRISTET")
pruef(r_unbefr["befristung"]["getroffen"] is False
      and "strukturierte Angabe" in r_unbefr["befristung"]["beleg"],
      "strukturierte Vertragsdauer schlaegt das Muster und nennt die Herkunft")

# --- 4. Erreichbarkeit -----------------------------------------------------
print("Arbeitsmodell:")
modell = Arbeitsmodell(cfg)
modellfaelle = [
    ("Homeoffice ist nach Absprache moeglich.", "hybrid",
     "'Homeoffice moeglich' ist hybrid, nicht remote"),
    ("Anteilig mobiles Arbeiten ist vorgesehen.", "hybrid", "'anteilig mobil' ist hybrid"),
    ("Die Stelle ist vollstaendig remote zu besetzen.", "remote", "vollstaendig remote"),
    ("Wir arbeiten remote-first.", "remote", "remote-first"),
    ("90 % Homeoffice, ein Praesenztag im Monat.", "remote", "90 % Homeoffice"),
    ("Wir erwarten durchgehende Praesenz.", "onsite", "durchgehende Praesenz"),
    ("Ein Text ohne jede Angabe zum Arbeitsort.", "unklar", "keine Angabe -> unklar"),
    ("Bewerbungen nur aus dem Umkreis (KEIN 100 % Homeoffice/Remote).", "unklar",
     "Verneinung wird nicht als remote gelesen"),
]
for text, erwartet, was in modellfaelle:
    got = modell.bestimme(text)["modell"]
    pruef(got == erwartet, f"{got:7s} · {was}")

pruef(modell.bestimme("3 Tage pro Woche vor Ort.")["praesenztage"] == 3,
      "Praesenztage als Ziffer gelesen")
pruef(modell.bestimme("Zwei Praesenztage pro Woche.")["praesenztage"] == 2,
      "Praesenztage als Wort gelesen")

print("Fahrzeitregeln:")
regel = Regelwerk(cfg)
pruef(regel.pruefe("onsite", 60, None)["erlaubt"] is False,
      "onsite bei 60 min faellt raus (Schwelle 45)")
pruef(regel.pruefe("hybrid", 60, None)["erlaubt"] is True,
      "dieselbe Stelle als hybrid bleibt drin (Schwelle 75)")
# `unklar` hat eine EIGENE Schwelle (60 min), strenger als hybrid und
# grosszuegiger als onsite. Begruendung steht in config.yaml: 225 von 268
# sichtbaren Stellen nennen gar kein Arbeitsmodell, die Hybrid-Schwelle war
# dafuer zu weich. Wichtig bleibt, dass `unklar` NICHT hart gefiltert wird.
pruef(regel.pruefe("unklar", 55, None)["erlaubt"] is True,
      "unklar bei 55 min bleibt drin — kein harter Ausschluss")
pruef(regel.pruefe("unklar", 70, None)["erlaubt"] is False,
      "unklar bei 70 min faellt raus (eigene Schwelle 60, nicht hybrid 75)")
pruef(regel.pruefe("hybrid", 70, None)["erlaubt"] is True,
      "belegtes Hybrid bei 70 min bleibt — Beleg schlaegt Vermutung")
pruef(regel.pruefe("unklar", 50, None)["erlaubt"] is True
      and regel.pruefe("onsite", 50, None)["erlaubt"] is False,
      "unklar ist grosszuegiger als onsite, sonst traefe es Verwaltungen")
budget = regel.pruefe("hybrid", 70, 4)
pruef(budget["erlaubt"] is False and budget["grund"] == "wochenbudget",
      f"4 Praesenztage a 70 min sprengen das Wochenbudget: {budget['hinweis']}")
pruef(regel.pruefe("hybrid", 70, 2)["erlaubt"] is True,
      "zwei Praesenztage a 70 min bleiben im Budget")
pruef(regel.pruefe("remote", 400, None)["erlaubt"] is True,
      "remote ist von der Fahrzeit unabhaengig")
pruef(regel.pruefe("hybrid", None, None)["erlaubt"] is True,
      "ohne ermittelbare Fahrzeit wird nicht gefiltert, sondern markiert")

print("Fahrzeit-Cache:")


class _ZaehlSession:
    """Zaehlt Zugriffe. Ein zweiter Aufruf desselben Orts darf nicht zaehlen."""

    def __init__(self):
        self.aufrufe = 0

    def get(self, *a, **k):
        self.aufrufe += 1
        raise RuntimeError("kein Netz im Test")

    def post(self, *a, **k):
        self.aufrufe += 1
        raise RuntimeError("kein Netz im Test")


tmp = Path(tempfile.mkdtemp(prefix="jobradar-test-"))
sess = _ZaehlSession()
fz = Fahrzeit({**cfg, "erreichbarkeit": {**cfg["erreichbarkeit"],
                                         "ors": {"cache": "fz.json"}}}, tmp, sess)
stelle = {"ort": "Siegen", "plz": "57072", "entfernung_km": 26}
erst = fz.fuer(stelle)
nach_erstem = sess.aufrufe
zweit = fz.fuer(dict(stelle))
pruef(erst == zweit, "zweiter Aufruf liefert dasselbe Ergebnis")
pruef(sess.aufrufe == nach_erstem,
      f"zweiter Aufruf loest keinen weiteren Zugriff aus ({sess.aufrufe})")
pruef(erst["geschaetzt"] is True and erst["quelle"] == "Luftlinie",
      f"ohne ORS_API_KEY wird geschaetzt und das ausgewiesen ({erst})")
pruef(fz.fuer({"ort": "Beeskow", "plz": "15848"})["minuten"] > 75,
      "Ort ausserhalb des PLZ-Rasters wird als weit geschaetzt")

# --- 5. Umfang und Entgelt -------------------------------------------------
print("Umfang und Entgelt:")
pruef(wochenstunden("Der Umfang betraegt 15 Stunden pro Woche.") == 15,
      "15 Wochenstunden gelesen")
pruef(wochenstunden("Vollzeit, unbefristet.") is None,
      "ohne Stundenangabe: None (kein Ausschluss)")
pruef(wochenstunden("Teilzeit ab 20 Stunden pro Woche bis Vollzeit 39 Stunden "
                    "pro Woche.") == 20,
      "bei Spanne zaehlt die Untergrenze")
entgelt = Entgelt(cfg)
pruef(entgelt.lies("Die Verguetung erfolgt nach Entgeltgruppe 9c TVöD.")
      is not None, "Entgeltgruppe wird erkannt")
pruef(entgelt.lies("Wir bieten ein attraktives Gehalt.") is None,
      "ohne Angabe: None")

# --- 6. Harte Filter in der Pipeline --------------------------------------
print("Harte Filter:")
fahrzeit_nah = Fahrzeit(cfg, tmp)
werkzeug = dict(screener=screener, arbeitsmodell=modell, fahrzeit=fahrzeit_nah,
                regelwerk=regel, passung=passung, entgelt=entgelt, cfg=cfg)


def durchlauf(titel, text, **extra):
    eintrag = {"id": "t:" + titel, "titel": titel, "arbeitgeber": "X",
               "ort": "Siegen", "plz": "57072", "entfernung_km": 20,
               "quelle": "Test", "url": "https://x"}
    eintrag.update(extra)
    return bewerte_eintrag(eintrag, text, zaehler=_leerer_zaehler(), **werkzeug)


hart = durchlauf("Referent", "Vorausgesetzt wird ein abgeschlossenes "
                             "Hochschulstudium der Germanistik.")
pruef(hart["gefiltert"] == "studium", "Studium zwingend (rot) faellt raus")

weich = durchlauf("Referent", "Ein abgeschlossenes Studium oder eine "
                              "vergleichbare Qualifikation wird erwartet.")
pruef(weich["gefiltert"] is None, "Studium ODER vergleichbar (gelb) bleibt drin")

kurz = durchlauf("Assistenz", "Die Stelle umfasst 15 Stunden pro Woche.")
pruef(kurz["gefiltert"] == "umfang", "15 Wochenstunden fallen raus")

ohne_angabe = durchlauf("Assistenz", "Wir bieten eine abwechslungsreiche Taetigkeit.")
pruef(ohne_angabe["gefiltert"] is None,
      "fehlende Stundenangabe schliesst nicht aus")

fern = durchlauf("Referent", "Wir erwarten durchgehende Praesenz.",
                 ort="Beeskow", plz="15848", entfernung_km=None)
pruef(fern["gefiltert"] == "fahrzeit", "zu weit entfernt faellt raus")

# Der Zieltest noch einmal durch die ganze Pipeline.
ziel_pipeline = durchlauf("Sachbearbeitung Wirtschaftsförderung", zieltext)
pruef(ziel_pipeline["gefiltert"] is None,
      "die getarnte Kommunikationsstelle ueberlebt alle harten Filter")
pruef(ziel_pipeline["passung"]["score"] >= 5,
      f"und behaelt ihren hohen Score ({ziel_pipeline['passung']['score']})")

# --- 7. Quellenausfall darf den Bestand nicht leeren ----------------------
print("Quellenausfall:")
import requests as _requests  # noqa: E402

from jobradar import scan as _scan  # noqa: E402


class _ToteSession:
    def get(self, *a, **k):
        raise _requests.RequestException("Verbindung abgewiesen (simuliert)")

    def post(self, *a, **k):
        raise _requests.RequestException("Verbindung abgewiesen (simuliert)")


bestand = {"stellen": {"ba:alt-1": {"id": "ba:alt-1", "titel": "Bestandsstelle",
                                    "zuletzt_gesehen": "2026-08-08T08:00:00Z"}},
           "laeufe": []}
vorher = json.dumps(bestand, sort_keys=True)
_echte_session = _scan.requests.Session
_scan.requests.Session = _ToteSession
try:
    _scan.scanne({**cfg, "seiten_quellen": [], "rss_quellen": [], "remote": {}},
                 bestand)
    pruef(False, "QuellenAusfall wurde nicht ausgeloest")
except QuellenAusfall as exc:
    pruef("BA-Abfragen fehlgeschlagen" in str(exc),
          "abgebrochen statt Bestand zu leeren")
finally:
    _scan.requests.Session = _echte_session
pruef(json.dumps(bestand, sort_keys=True) == vorher,
      "Bestand unveraendert geblieben")

# --- 8. Normalisierung der BA-Antwort (echtes v6-Schema) ------------------
print("Normalisierung:")
echte_v6 = {
    "stellenangebotsTitel": "Teilsachgebietsleiter Öffentlichkeitsarbeit (m/w/d)",
    "hauptberuf": "Medienwissenschaftler/in",
    "firma": "Bundesamt für das Personalmanagement der Bundeswehr",
    "referenznummer": "13270-2026-00006447-1-S",
    "stellenlokationen": [{"adresse": {"plz": "50737", "ort": "Köln"}}],
    "entfernung": 58,
    "datumErsteVeroeffentlichung": "2026-07-30",
    "eintrittszeitraum": {"von": "2026-12-01"},
    "vertragsdauer": "UNBEFRISTET",
}
echt = BundesagenturQuelle.normalisiere(echte_v6, "kommunikation", "Öffentlichkeitsarbeit")
pruef(echt["id"] == "ba:13270-2026-00006447-1-S"
      and echt["ort"] == "Köln" and echt["entfernung_km"] == 58
      and echt["veroeffentlicht"] == "2026-07-30",
      "v6-Felder korrekt uebersetzt")

print("RSS-Feldtrennung:")
summary = ("Arbeitgeber: Landkreis Oder-Spree Ort: 15848 Beeskow "
           "Bewerbungsfrist: 06.09.2026 00:00 Veröffentlichungsende: 07.09.2026")
pruef(RssQuelle._arbeitgeber(summary, "") == "Landkreis Oder-Spree",
      "Arbeitgeber endet an der naechsten Feldmarke")
pruef(RssQuelle._frist(summary) == "2026-09-06", "Bewerbungsfrist gelesen")
pruef(RssQuelle._plz("15848 Beeskow") == "15848", "PLZ aus dem Ort gezogen")

print("Datum:")
for roh, erwartet in [("2026-08-05", "2026-08-05"), ("05.08.2026", "2026-08-05"),
                      ("Wed, 05 Aug 2026 09:12:00 +0200", "2026-08-05"),
                      (None, None)]:
    pruef(parse_date(roh) == erwartet, f"{roh!r} -> {parse_date(roh)}")

# --- 9. Dashboard ----------------------------------------------------------
print("Dashboard:")
zustand = {"stellen": {}, "laeufe": [{
    "zeit": "2026-08-11T06:00:00Z", "gefunden": 4, "neu": 3, "gesamt": 4,
    "sichtbar": 3, "zusammengefuehrt": 2, "ohne_beschreibung": 1,
    "gefiltert": {"fahrzeit": 5, "umfang": 1, "studium": 2, "wochenbudget": 0},
}]}
for i, (titel, text, arch) in enumerate([
        ("Sachbearbeitung Wirtschaftsförderung", zieltext, "angrenzend"),
        ("Referent Öffentlichkeitsarbeit", werbetext, "kommunikation"),
        ("Teamlead SAP", "Vorausgesetzt wird ein abgeschlossenes Studium.", "marketing"),
        ("Stelle ohne Text", "", "video")]):
    e = durchlauf(titel, text)
    e["id"] = f"x:{i}"
    e["archetyp"] = arch
    e["veroeffentlicht"] = "2026-08-05"
    e["neu"] = i < 2
    zustand["stellen"][e["id"]] = e

ziel_datei = baue_dashboard(cfg, zustand, tmp / "index.html")
doc = ziel_datei.read_text(encoding="utf-8")
for pflicht in ['data-sort="score"', 'data-sort="fahrzeit"', 'data-sort="datum"',
                'data-filter="zeigeGefiltert"', 'data-filter="nurPassend"',
                'data-farbe="modell"', 'data-farbe="alter"', 'data-farbe="kategorie"',
                'class="score', "Ausgefilterte zeigen", "<summary>Details</summary>",
                'id="karte"', 'id="daten"', "Duplikate zusammengeführt"]:
    pruef(pflicht in doc, f"im Dashboard vorhanden: {pflicht}")
pruef('data-gefiltert="studium"' in doc,
      "ausgefilterte Stellen bleiben im Dokument, nur ausgeblendet")

# Gruppen muessen nach ihrem besten Treffer geordnet sein, nicht nach `rang`.
# Sonst sortiert jede Kategorie nur fuer sich und die staerkste Stelle des
# Boards versteckt sich in Abschnitt fuenf.
import re as _re  # noqa: E402
folge = _re.findall(r'section class="gruppe" data-archetyp="([^"]+)"', doc)
pruef(folge and folge[0] == "angrenzend",
      f"Gruppe mit dem hoechsten Score steht oben (Reihenfolge: {folge})")
pruef('id="gruppen"' in doc,
      "Gruppen liegen in einem Behaelter, damit JS sie umsortieren kann")
pruef("function bestwert" in doc,
      "Sortierung wirkt auch auf Gruppenebene")
pruef("nicht mehr gelistet" not in doc,
      "kein Altbestand im Dokument (verfall_tage: 0)")

# Ausgefilterte Zeilen muessen schon AUSGELIEFERT versteckt sein. Sonst rendert
# der Browser erst alle Zeilen und das Skript raeumt danach auf — sichtbar als
# Aufblitzen einer langen Liste, die zusammenklappt.
import re as _re2  # noqa: E402
artikel = _re2.findall(r'<article class="([^"]*)"( hidden)?', doc)
gefilterte = [(k, h) for k, h in artikel if "gefiltert" in k]
pruef(gefilterte and all(h for _, h in gefilterte),
      f"ausgefilterte Zeilen tragen `hidden` im Markup ({len(gefilterte)} geprueft)")
pruef("line-through" not in doc,
      "kein Durchstreichen — die Grundmarke benennt den Grund")

# Belegstellen gehoeren in den aufklappbaren Teil, nicht in die Uebersicht.
kopf = doc.split("<details>")[0] if "<details>" in doc else doc
pruef("Studium zwingend:" not in kopf,
      "Belegstellen stehen unter Details, nicht in der Kopfzeile")
pruef(doc.count("<details>") >= 3,
      f"jede Zeile hat einen aufklappbaren Teil ({doc.count('<details>')})")

# Ohne Beschreibung gibt es keinen Score — und der Platzhalter muss sichtbar
# sein, damit "kein Urteil" nicht wie "Score 0" aussieht.
pruef('class="score leer"' in doc,
      "Stellen ohne Beschreibung zeigen einen Platzhalter statt einer Zahl")

# Die Karte darf keine fremden Server anfragen (Grenze 7).
# Nur ladende Ressourcen pruefen — Anzeigenlinks (<a href>) sind Ziele zum
# Anklicken, keine Aufrufe beim Oeffnen der Seite.
import re as _re3  # noqa: E402
laden = _re3.findall(
    r'<(?:script|link|img|iframe|source|video|audio)[^>]*?'
    r'(?:src|href)=["\'](https?://[^"\']+)', doc, _re3.I)
laden += _re3.findall(r'@import\s+url\(["\']?(https?://[^"\')]+)', doc, _re3.I)
pruef(not laden, f"Dashboard laedt nichts von fremden Servern ({laden[:3]})")
pruef("openstreetmap" not in doc.lower() and "tile" not in doc.lower(),
      "keine Kartenkacheln von fremden Servern")

for spur in (ROOT / "data" / "jobs.json", ROOT / "site" / "index.html"):
    pruef(not spur.exists() or spur.stat().st_mtime < start_zeit,
          f"echter Bestand unberuehrt: {spur.name}")

print()
if fehler:
    print(f"{len(fehler)} FEHLER:")
    for f in fehler:
        print("  -", f)
    raise SystemExit(1)
print("Alles durchgelaufen.")
