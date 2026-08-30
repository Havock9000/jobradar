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
config.yaml            Alles Änderbare. Suchbegriffe, Scoring-Gewichte,
                       Erreichbarkeitsregeln, Quellen. Code bleibt unberührt.
jobradar/scan.py       Quellen (BA, RSS, Karriereseiten) und Lauflogik
jobradar/lauf.py       Pipeline-Schritt je Anzeige + Sortierschlüssel
jobradar/dedupe.py     Zusammenführung über Quellen hinweg
jobradar/passung.py    Inhaltliches Scoring am ANZEIGENTEXT
jobradar/erreichbarkeit.py  Arbeitsmodell, Fahrzeit, Wochenbudget
jobradar/merkmale.py   Wochenstunden und Entgeltgruppe aus dem Text
jobradar/jobspy_quelle.py   Optionale Quelle Indeed/LinkedIn (aus)
jobradar/seiten.py     Karriereseiten-Watcher mit robots.txt-Prüfung
jobradar/render.py     Erzeugt site/index.html aus data/jobs.json
data/jobs.json         Zustand, inkl. `_text` (Anzeigentext) je Stelle
data/fahrzeiten.json   Fahrzeit-Cache Ort → Minuten
site/                  Das EINZIGE, was nach GitHub Pages geht.
tests/                 Offline-Tests, laufen ohne Netz
.github/workflows/     Täglicher Lauf 05:40 UTC, Commit, Pages-Deploy
```

Pipeline:
`Quellen → Dedupe → Screening → Erreichbarkeit → harte Filter → Scoring → Render`

Dedupe kommt vor dem Screening, weil Screening der teure Schritt ist. Die
harten Filter kommen vor dem Scoring, weil eine unerreichbare Stelle keinen
Score braucht — bewertet wird trotzdem alles, damit unter „Ausgefilterte
zeigen" prüfbar bleibt, ob ein Filter zu breit greift.

## Die konzeptionelle Umstellung vom 11.08.2026

**Vorher** entschied der Titel: `ausschluss_titel` entfernte Anzeigen, deren
Berufsbezeichnung ein Muster traf. **Jetzt** entscheidet der Anzeigentext.

Der Grund ist empirisch. Berufsbezeichnungen sind in diesem Feld unzuverlässig
— dieselbe Tätigkeit heißt „Referent*in Öffentlichkeitsarbeit",
„Sachbearbeitung Kommunikation", „Mitarbeiter*in Stabsstelle",
„Online-Redakteur*in" oder „Marketingassistenz". Der alte Filter hat dadurch
nachweislich Passendes gekillt: „Performance Marketing Manager (m/w/d)" in
57520 Niederdreisbach, 25 km entfernt, „bis zu 100 % Remote" — spurlos
verschwunden.

Gemessen am ersten Lauf nach dem Umbau: **49 von 278** sichtbaren Stellen
hätte der alte Titelfilter entfernt, 2 davon unter den zehn
höchstbewerteten. Das ist der Gradmesser; sinkt er gegen null, war der Umbau
umsonst.

`ausschluss_titel` ist nicht gelöscht. Die Muster stehen weiter in der Config
und wirken als Abwertung (`passung.reibung.titel_abwertung`, −2) mit
sichtbarem Beleg. `ausschluss_titel_hart: false` dokumentiert das.

## Harte Filter — abschließende Liste

Nur diese drei entfernen etwas aus der Standardansicht:

1. **Erreichbarkeit.** Fahrzeit gegen die Schwelle des Arbeitsmodells
   (onsite 45 min, hybrid 75 min, remote unbegrenzt), plus Wochenbudget
   (Präsenztage × Fahrzeit × 2 ≤ 450 min).
2. **Umfang** unter 20 Wochenstunden — aber nur, wenn eine Stundenzahl im
   Text steht. Fehlende Angabe schließt nicht aus.
3. **Studium zwingend** (Status rot). Status gelb — Studium *oder*
   vergleichbare Qualifikation — bleibt sichtbar; das ist der Fall, in dem
   Berufserfahrung greift.

Vergütung wird **nicht** gefiltert: fehlt in der BA-Datenbank meistens, und
„keine Angabe" ist kein Ausschluss. Steht eine Entgeltgruppe im Text, wird
sie angezeigt.

## Erreichbarkeit im Detail

`unklar` wird **nicht** gefiltert, sondern gegen die Hybrid-Schwelle geprüft
und markiert. Forschungseinrichtungen und Verwaltungen nennen das Modell
selten; ein harter Ausschluss killt genau die Stellen, auf die es ankommt.
Im ersten Lauf standen 234 von 278 sichtbaren Stellen auf `unklar` — das ist
die Regel, nicht die Ausnahme.

Abgrenzung, die leicht falsch läuft: **„Homeoffice möglich" und „anteilig
mobil" sind hybrid, nicht remote.** Nur eine ausdrückliche Anteilsangabe ab
90 % oder „vollständig remote" zählt als remote.

Ohne `ORS_API_KEY` wird die Fahrzeit geschätzt (Luftlinie × 1.35 ÷ 65 km/h,
sonst PLZ-Raster) und im Dashboard grau als geschätzt ausgewiesen. **Kein
stiller Fallback** — die Fahrzeit entscheidet über Aufnahme oder Ausschluss.
ORS liefert reine PKW-Zeit; bei Bahnanbindung weicht der Tür-zu-Tür-Wert ab.

## Stellschrauben

- `passung.aufgaben[*].gewicht` — was zählt wie viel. Mehr Bewegtbild? Dort heben.
- `passung.reibung[*].gewicht` — CMS bewusst nur −1 (fehlende Erfahrung, kein
  Ausschluss), Ehrenamt −3 als schwerstes Muster, aber **nicht mehr hart
  gefiltert**: die Entscheidung trifft der Mensch, nicht die Regex.
- `dedupe.titel_aehnlichkeit: 0.85` — gemessen, siehe Kommentar in config.yaml.
  Muss über 0.769 und höchstens 0.923 liegen.
- `erreichbarkeit.*` — Schwellen und Wochenbudget.

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
1. **Indeed/LinkedIn: kontrolliert revidiert am 11.08.2026.** Der Zugang
   existiert jetzt als `jobradar/jobspy_quelle.py`, steht aber in `config.yaml`
   auf `jobspy.aktiv: false`. Nüchtern: Die Nutzungsbedingungen der Portale
   untersagen automatisierten Zugriff; das Einschalten ist eine Entscheidung
   des Betreibers, keine Voreinstellung. **Nicht eigenmächtig einschalten.**
   Technisch dazu: LinkedIn blockt Rechenzentrums-IPs zuverlässig, auf
   GitHub Actions (Azure) bleibt der LinkedIn-Teil ohne Wohn-Proxy leer —
   das ist erwartet und kein Fehler. Indeed/Deutschland liefert dagegen
   echte Volltexte (geprüft: 8 von 8 Treffern, 1.789–6.816 Zeichen).
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

## Forschungseinrichtungen (geprüft 11.08.2026)

**Keine** der elf geprüften Einrichtungen hat JobPosting-Markup (JSON-LD) —
weder auf der Übersicht noch auf der Einzelanzeige. Alle sind daher HTML-Fälle
(`markup: false`), bei denen `seiten.py` den Volltext aus dem Seiten-HTML zieht.

Aufgenommen:

- **Universität Bonn** — 32 echte Anzeigenlinks auf der Übersicht, Titel sauber
  im Linktext, Einzelanzeigen serverseitig gerendert. Rund 40 km; damit hängt
  die Aufnahme am Arbeitsmodell (hybrid ja, onsite nein).

Nicht aufgenommen, mit Grund:

| Einrichtung | Grund |
|---|---|
| DZNE (jobs.dzne.de) | Liste per JavaScript nachgeladen, 5 Links auf 26 kB |
| Universität Siegen | alle geprüften Pfade 404, richtige URL nicht ermittelbar |
| Helmholtz (jobs.helmholtz.de) | Host nicht erreichbar (ConnectionError) |
| MPG, Fraunhofer, DLR | bundesweite Portale ohne festen Ort — ohne Ortsangabe greift die Fahrzeitprüfung nicht |
| Forschungszentrum Jülich | ~95 km, außerhalb jeder Pendelgrenze |
| MPI Neurobiologie des Verhaltens | alle geprüften Pfade 404 |

**academics.de hat keinen Feed.** Weder `/rss`, `/feed` noch `/jobs/rss`
(alle 404), und im HTML steht kein `alternate`-Link. Die robots.txt enthält
zusätzlich einen ausdrücklichen Hinweis, dass automatisierter Zugriff ohne
Erlaubnis untersagt ist. Deshalb **nicht scrapen** — dort einen eigenen
Suchagenten abonnieren, wie bei Interamt auch.

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

## Suchbegriffe

Am 11.08.2026 auf sieben Cluster verbreitert (kommunikation, redaktion, video,
wissenschaftskommunikation, marketing, angrenzend). Jeder Begriff geht
**einzeln** an die BA-API — kombinierte Begriffe liefern messbar schlechtere
Treffer ("Stadtmarketing Tourismus" → 0, "Stadtmarketing" → 3).

Der Cluster `angrenzend` ist der eigentliche Zweck des Umbaus: Stellen, deren
Titel nichts mit Kommunikation zu tun hat, deren Aufgabenbeschreibung aber
überwiegend daraus besteht. Ob so eine Stelle sichtbar wird, entscheidet der
Score am Text — im ersten Lauf kamen darüber 15 Stellen in die Standardansicht.

Weiterhin gilt: **nicht eigenmächtig umschreiben.** Formulierung ist Technik
und darf angepasst werden, Zielrichtung ist Strategie und gehört dem Nutzer.

Zwei früher geprüfte und widerlegte Hypothesen, bitte nicht neu durchspielen:
Begriffe kürzen tauscht null Treffer gegen Rauschen ("Quereinstieg" → 57
Treffer im Radius, u.a. Kunstharzbodenbeschichtung), und ein größeres
Zeitfenster (100 statt 30 Tage) bringt exakt null zusätzliche Treffer.

## Ausbau

Kandidaten, in dieser Reihenfolge:

- **ORS_API_KEY setzen.** Der größte Hebel für die Qualität. Ohne ihn sind
  alle Fahrzeiten geschätzt; im ersten Lauf entschied damit eine Luftlinien-
  Näherung über 174 Ausschlüsse. Kostenloser Key bei openrouteservice.org.
- **Volltext für service.bund.de-Einträge.** Deren Detailseiten sind
  robots-erlaubt und liefern ~8800 Zeichen. Ohne das bleiben RSS-Treffer
  ohne Beschreibung, also ohne Score und ohne Arbeitsmodell — sie landen
  automatisch auf `unklar`.
- **RSS serverseitig auf den Umkreis einschränken.** Von 200 Feed-Einträgen
  überlebt ein Bruchteil die Fahrzeitprüfung. Auf service.bund.de eine Suche
  mit Ortsangabe bauen und den RSS-Link abgreifen. Muss der Nutzer machen,
  die URL lässt sich nicht raten.
- **Fristerkennung für BA-Anzeigen** aus dem Fließtext ("Bewerbungsfrist",
  "Bewerbungen bis zum", "bis spätestens").
- **E-Mail-Benachrichtigung** bei neuen Treffern mit hohem Score.

## Tests

```bash
python tests/test_offline.py   # Dedupe, Scoring, Erreichbarkeit, harte Filter
python tests/test_seiten.py    # Linkextraktion, robots.txt-Logik
python -m jobradar.scan --offline   # Dashboard neu bauen ohne Netz
```

Beide laufen ohne Netz und müssen grün bleiben.

**Der wichtigste Test** steht unter „Scoring": Eine Stelle mit dem Titel
`Sachbearbeitung Wirtschaftsförderung`, deren Aufgabentext Pressearbeit,
Newsletter und Veranstaltungsdokumentation enthält, muss einen hohen Score
bekommen und alle harten Filter überleben. Das ist der Zweck des ganzen
Umbaus — schlägt er fehl, ist die Arbeit nicht fertig.

Ebenfalls abgesichert: Ein Titel, der `ausschluss_titel` trifft, darf nur
abgewertet und nicht entfernt werden. Und der Dedupe-Negativfall
(`Referent Öffentlichkeitsarbeit` vs. `… Schwerpunkt Video`) muss getrennt
bleiben — daran hängt die Schwelle 0.85.

## Umgangston

Der Nutzer will Widerspruch mit Belegstelle, keine Zustimmung. Wenn eine
Designentscheidung hier fragwürdig ist, benenne den konkreten Punkt. Wenn etwas
unklar ist, frage, statt zu raten. Keine Statusberichte über selbst erledigte
Zwischenschritte.
