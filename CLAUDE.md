# CLAUDE.md

Kontext für Claude Code. Vor dem ersten Eingriff vollständig lesen.

## Was das hier ist

Ein persönliches Stellenradar. Es fragt täglich drei öffentliche Quellen ab,
screent die Anzeigen gegen die Ausschlusskriterien des Nutzers und
veröffentlicht das Ergebnis als statische Seite über GitHub Pages.

Der Nutzer ist Mediengestalter Bild und Ton mit Berufserfahrung in
Videoproduktion und Performance Marketing, wohnt bei 57577 im Westerwald und
sucht Stellen in Öffentlichkeitsarbeit, Medienproduktion, kommunaler Verwaltung
und Medienbildung. Er ist technisch versiert — erkläre nicht, was Python ist,
aber begründe Designentscheidungen.

## Architektur

```
config.yaml            Alles Änderbare. Suchbegriffe, Screening-Muster,
                       Quellen, Ausschlussregeln. Code bleibt unberührt.
jobradar/scan.py       Hauptlauf: sammeln, screenen, Zustand fortschreiben
jobradar/seiten.py     Karriereseiten-Watcher mit robots.txt-Prüfung
jobradar/render.py     Erzeugt site/index.html aus data/jobs.json
data/jobs.json         Zustand. Enthält auch verschwundene Anzeigen bis zum
                       Verfall, damit "neu seit letztem Lauf" funktioniert.
site/                  Das EINZIGE, was nach GitHub Pages geht. Enthält nur
                       index.html. Nichts anderes hier ablegen.
tests/                 Offline-Tests, laufen ohne Netz
.github/workflows/     Täglicher Lauf 05:40 UTC, Commit, Pages-Deploy
```

Datenfluss: `scan.py` sammelt aus drei Quellen → dedupliziert über `id` →
Titel-Ausschlussfilter → **Ortsfilter** (`Umkreis`, PLZ-Präfixe) → Volltext nur
für **neue** Einträge nachladen → `Screener` erzeugt die drei Statusfelder →
Merge mit Bestand → `render.py`.

## Die drei Quellen

Stand 09.08.2026 — alle drei im echten Lauf verifiziert.

| Quelle | Zugriff | Status |
|---|---|---|
| Bundesagentur für Arbeit | JSON, `/pc/v6/jobs`, Header `X-API-Key: jobboerse-jobsuche` | **läuft** |
| service.bund.de | RSS je Suchabfrage (`&jobsrss=true`) | **läuft**, aber siehe unten |
| Karriereseiten | HTML + JobPosting-Markup (JSON-LD), nach robots.txt-Prüfung | **läuft**, mager |

Was der erste echte Lauf ergeben hat, damit es niemand neu herausfinden muss:

- **Die BA-Suche lag auf `/pc/v4/app/jobs` und war tot.** Das Gateway antwortet
  auf allen alten Pfaden mit `403 "No match found for request"` — eine Routing-,
  keine Auth-Meldung. Der API-Key ist unverändert gültig. Zusätzlich hatte die
  Antwort neue Feldnamen (`ergebnisliste` statt `stellenangebote`, `firma` statt
  `arbeitgeber`, `stellenlokationen[0].adresse` statt `arbeitsort`,
  `stellenangebotsBeschreibung` statt `stellenbeschreibung`). Beides zusammen
  hätte auch nach dem Pfad-Fix zu 0 Treffern bei HTTP 200 geführt. `suche()`
  loggt darum laut, wenn `ergebnisliste` fehlt — **diese Warnung nicht
  entfernen**, sie ist die einzige Sicherung gegen den nächsten stillen Bruch.
- **Der Detail-Abruf liegt weiter auf v4** (`/pc/v4/jobdetails/{base64}`),
  `v6/jobdetails` existiert nicht. Base64-Padding ist egal.
- **Die RSS-Feeds funktionieren**, liefern aber nur Metadaten (111–176 Zeichen:
  Arbeitgeber, Ort, Bewerbungsfrist) und **keinen Anzeigentext**. Screening auf
  RSS-Einträgen läuft daher praktisch auf dem Titel. Die Detailseiten
  (`service.bund.de/IMPORTE/…`) sind robots-erlaubt und enthalten ~8800 Zeichen
  Fließtext — das ist der offene Weg, falls echtes Screening gewünscht ist.
- **Die Feeds sind bundesweit.** Ohne den `Umkreis`-Filter stehen Stellen aus
  Beeskow und Hildesheim im Dashboard; von 200 Feed-Einträgen überlebt etwa
  einer. Besser wäre eine serverseitig auf den Umkreis eingeschränkte Suche auf
  service.bund.de, deren RSS-Link man abgreift.

## Harte Grenzen

Diese Punkte nicht ohne Rückfrage ändern:

0. **Kein Google-Scraping.** Google hat keine Jobs-API mehr und untersagt das
   Auslesen der Suchergebnisse. Der eingebaute Weg ist der richtige: JobPosting-
   Markup (JSON-LD) direkt von den Arbeitgeberseiten lesen — dieselbe Quelle,
   aus der Google selbst zieht. Nicht durch einen Google-Scraper ersetzen.
1. **Kein LinkedIn, Indeed, StepStone.** Deren AGB untersagen automatisierten
   Zugriff. Der Nutzer hat danach gefragt; die Antwort war Nein, mit Begründung
   im README. Wenn er erneut fragt, verweise darauf statt neu zu diskutieren.
2. **Kein Zugriff hinter Login**, keine Umgehung technischer Sperren, keine
   kostenpflichtigen Portale (WILA Arbeitsmarkt).
3. **robots.txt wird respektiert.** Die Prüfung in `seiten.py` nicht
   auskommentieren, auch nicht "nur zum Testen".
4. **Ausschlussfilter greift nur gegen den Titel.** Absicht: Eine Anzeige, die
   Social Media als eine Aufgabe unter vielen nennt, soll erhalten bleiben. Nur
   Rollen, die selbst danach benannt sind, fliegen raus. Nicht auf Volltext
   ausweiten.
5. **Belegstellen bleiben sichtbar.** Jedes Statusfeld zeigt die Textstelle,
   aus der es folgt. Mustererkennung produziert Fehlurteile; ohne Beleg merkt
   der Nutzer das nicht. Nicht wegoptimieren.
6. **Nach Pages geht nur `site/`.** Der Workflow hatte `path: .` und hat damit
   `CLAUDE.md` und `config.yaml` unter der öffentlichen URL ausgeliefert. Nie
   auf das Wurzelverzeichnis zurückstellen.
7. **Keine Web-Fonts, kein CDN, kein Analytics im Dashboard.** Das Dashboard lud
   Google Fonts und meldete damit bei jedem Öffnen IP und aufgerufene Seite an
   Google — ausgerechnet bei einer Seite, die die laufende Stellensuche abbildet.
   `site/index.html` macht jetzt null Fremdaufrufe. Das soll so bleiben.
8. **Der Ortsfilter gilt für alle Quellen, auch die BA.** Deren `umkreis`-
   Parameter meint 60 km Luftlinie und reicht bis Bonn und Köln — der Nutzer
   will höchstens ~50 min Fahrt. Sich auf die Vorfilterung der Quelle zu
   verlassen heißt, genau die zu weite Grenze zu übernehmen.
9. **Ein Quellenausfall bricht den Lauf ab, statt den Bestand zu leeren.**
   `QuellenAusfall` fliegt, wenn *alle* BA-Abfragen oder *alle* RSS-Feeds
   scheitern, und `main()` beendet sich mit Code 1, **bevor** irgendetwas
   geschrieben wird. Grund: Der Merge markiert jede nicht wiedergefundene
   Stelle als `entfernt` — ein Totalausfall sähe im Dashboard exakt aus wie
   "alle Anzeigen zurückgezogen", bei Exitcode 0. Diese Prüfung nicht
   entfernen und nicht zu "einzelne Fehler tolerieren" aufweichen.
10. **Tests fassen `data/jobs.json` nicht an.** `test_offline.py` schrieb früher
   direkt dorthin und hat bei jedem Lauf den Bestand samt "neu seit letztem
   Lauf" zerstört. Er schreibt jetzt in ein Temp-Verzeichnis und prüft am Ende
   selbst nach, dass der echte Bestand unberührt blieb.

## Screening-Kriterien des Nutzers

Drei Felder pro Anzeige, konfiguriert unter `screening` in `config.yaml`:

- **S — Studium.** Rot bei Studium ohne genannte Alternative, gelb bei "Studium
  oder vergleichbare Qualifikation", grün wenn nichts gefordert. Der Nutzer hat
  eine Berufsausbildung, kein Studium. Gelb ist für ihn die interessanteste
  Kategorie, nicht grün — dort sitzen die anspruchsvolleren Stellen, die er
  trotzdem erreichen kann. **Stellen mit Studiumspflicht werden markiert, nicht
  gefiltert.** Das war eine ausdrückliche Entscheidung.
- **E — Ehrenamtslogik.** Rot, wenn der Text auf Vereins-, Verbands- oder
  Ehrenamtsbetreuung hinweist. Das ist sein Knockout-Kriterium: Rollen, deren
  Durchsatz an Personen hängt, die nicht weisungsgebunden sind.
- **B — Befristung.** Das Muster nutzt `(?<!un)befristet`, sonst schlägt
  "unbefristet" an. Beim Ändern daran denken. **Bei BA-Anzeigen schlägt die
  strukturierte Angabe `vertragsdauer` das Muster** — die Regex rät, dieses Feld
  weiß es. Der Beleg nennt dann die Herkunft ("strukturierte Angabe der BA"),
  damit im Dashboard sichtbar bleibt, worauf das Urteil beruht (Grenze 5).
  Bei `KEINE_ANGABE` greift wieder das Muster.

## Stand der Karriereseiten (geprüft 09.08.2026)

Alle drei rendern serverseitig, keine hat JobPosting-Markup auf der Übersicht.

- **Biologische Station Rhein-Sieg** — technisch in Ordnung, hat aber derzeit
  keine offene Stelle. Null Treffer ist hier das richtige Ergebnis, nicht ein
  Fehler. Quelle bleibt drin.
- **Kreisverwaltung Altenkirchen — entfernt.** Führt keine eigenen Stellen mehr,
  sondern verweist auf Interamt — und aus Interamt importiert service.bund.de,
  über das die Stellen ohnehin hereinkommen. Lieferte nur Navigationsrauschen.
- **NABU Rheinland-Pfalz** — die einzige Quelle mit echten Anzeigen, aber als
  **PDF**. Daraus ist kein JSON-LD zu holen, das Screening läuft dort zwangs-
  läufig auf dem Linktext. `details_folgen` steht deshalb auf `false`; die
  Detailseiten sind zusätzlich per robots.txt gesperrt.

Neue Quelle prüfen weiterhin mit `python -m jobradar.seiten "<url>"`. Meldet der
Test viel HTML aber keine Treffer, rendert die Seite per JavaScript und ist so
nicht auslesbar — Quelle melden, nicht stillschweigend löschen.

## Suchbegriffe: nicht neu verhandeln

Die Kalibrierung ist am 09.08.2026 gemessen worden, die Ergebnisse stehen als
Kommentar über `archetypen` in `config.yaml`. Kurzfassung: 18 von 34 Begriffen
liefern null, und **das ist überwiegend korrekt**. Beide naheliegenden
Gegenmaßnahmen wurden geprüft und sind widerlegt — Begriffe kürzen tauscht null
Treffer gegen Rauschen ("Quereinstieg" → 57 Treffer, u.a. Kunstharzboden-
beschichtung), und ein größeres Zeitfenster bringt exakt null zusätzliche
Treffer. Der Suchraum ist real dünn. Wer mehr will, muss am Radius drehen.

Unverändert gilt: **nicht eigenmächtig umschreiben.** Formulierung ist Technik
und darf angepasst werden, Zielrichtung ist Strategie und gehört dem Nutzer.

## Ausbau

Kandidaten, in dieser Reihenfolge:

- **RSS serverseitig auf den Umkreis einschränken.** Der größte Hebel. Von 200
  Feed-Einträgen überlebt derzeit einer den Ortsfilter — der Rest ist bundesweit
  geladenes Rauschen. Auf service.bund.de eine Suche mit Ortsangabe bauen und
  den RSS-Link abgreifen. Muss der Nutzer machen, die URL lässt sich nicht raten
  (die alten Feed-URLs waren genau so entstanden).
- **Fristerkennung ausweiten.** `validThrough` aus JSON-LD ist umgesetzt, die
  Bewerbungsfrist aus dem RSS-`summary` ebenfalls. Offen: Fristen aus dem
  Fließtext der BA-Anzeigen ziehen (Muster "Bewerbungsfrist", "Bewerbungen bis
  zum", "bis spätestens"). Derzeit hat nur 1 von 12 Stellen eine Frist.
- **Volltext für service.bund.de-Einträge.** Deren Detailseiten sind robots-
  erlaubt und liefern ~8800 Zeichen. Ohne das bleibt bei RSS-Treffern
  `nur_titel: true` und die grünen Statusfelder sind nichtssagend.
- **E-Mail-Benachrichtigung** bei neuen Treffern, damit er nicht täglich das
  Dashboard aufrufen muss. GitHub Actions kann das ohne Zusatzdienst.
- **Historie** — wie viele passende Stellen tauchen pro Monat auf? Beantwortet
  die eigentliche strategische Frage: Ist der Suchraum groß genug. Nach dem
  ersten Lauf lautet die vorläufige Antwort: eher nicht.

## Tests

```bash
python tests/test_offline.py   # Ausschlussfilter, Screening, Datum, Rendering
python tests/test_seiten.py    # Linkextraktion, robots.txt-Logik
python -m jobradar.scan --offline   # Dashboard neu bauen ohne Netz
```

Beide Tests laufen ohne Netz und müssen grün bleiben. Wer `config.yaml` ändert,
prüft mit `test_offline.py`, ob der Ausschlussfilter noch das Richtige trifft —
er testet ausdrücklich auch, was **nicht** ausgeschlossen werden darf.

## Umgangston

Der Nutzer will Widerspruch mit Belegstelle, keine Zustimmung. Wenn eine
Designentscheidung hier fragwürdig ist, benenne den konkreten Punkt. Wenn etwas
unklar ist, frage, statt zu raten. Keine Statusberichte über selbst erledigte
Zwischenschritte.
