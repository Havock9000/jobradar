# Jobradar

Fragt täglich öffentliche Quellen nach Stellenanzeigen ab, bewertet den
**Anzeigentext** gegen ein Aufgabenprofil, prüft Fahrzeit und Arbeitsmodell und
veröffentlicht das Ergebnis als statische Seite.

**Quellen**

| Quelle | Zugriff | Abdeckung |
|---|---|---|
| Bundesagentur für Arbeit | inoffizielle JSON-API (`X-API-Key: jobboerse-jobsuche`) | größte Stellendatenbank Deutschlands, öffentlich und privat |
| service.bund.de | RSS je Suchabfrage (`&jobsrss=true`) | Bund, Länder, Kommunen |
| Karriereseiten | HTML + JobPosting-Markup (JSON-LD), nach robots.txt-Prüfung | Arbeitgeber ohne Feed |

Interamt hat keinen offenen Feed und arbeitet mit sessionverschlüsselten URLs.
Dort stattdessen den eigenen Jobticker per E-Mail abonnieren — die Überschneidung
mit service.bund.de ist ohnehin hoch.

### Warum kein Google for Jobs

Google hat seine Jobs-API eingestellt; die Suchergebnisse zu scrapen verstößt
gegen die Nutzungsbedingungen und wird technisch geblockt. Entscheidend ist
aber die Umkehrung: Eine Anzeige erscheint bei Google for Jobs nur, wenn auf
der Stellenseite JobPosting-Markup nach schema.org liegt. Google ist also eine
Entdeckungsschicht, keine Datenquelle — dieselben Daten stehen maschinenlesbar
auf der Arbeitgeberseite.

Genau die liest `seiten.py` mit `details_folgen: true` aus und gewinnt daraus
Volltext, Veröffentlichungsdatum und Bewerbungsfrist. Bei kleinen Vereinen und
Kommunen fehlt das Markup oft; dann bleibt es beim Titel, und das Dashboard
markiert die Zeile mit *nur Titel*.

## Was standardmäßig nicht abgefragt wird

Indeed und LinkedIn sind seit dem 11.08.2026 über `jobradar/jobspy_quelle.py`
technisch angebunden, stehen in `config.yaml` aber auf `jobspy.aktiv: false`.
Näheres unter „Indeed und LinkedIn" weiter unten.

Nicht abgefragt bleiben: alles hinter einem Login, Portale mit
kostenpflichtigem Zugang (z. B. WILA Arbeitsmarkt) — die dort abonnierte
Ausgabe ist der vorgesehene Weg — und Google-Suchergebnisse.

Das Modul `jobradar/seiten.py` bewegt sich bewusst innerhalb dieser Grenze:
nur öffentliche Seiten ohne Login, robots.txt vor jedem Abruf geprüft,
sprechender User-Agent, eine Anfrage pro Seite und Lauf.

**Hinweis zum Zustand:** Seit dem Umbau auf Textscoring liegt der Anzeigentext
jeder Stelle als `_text` in `data/jobs.json` — sonst könnte eine Änderung an
Gewichten oder Mustern den Bestand nicht neu bewerten, ohne alles erneut
abzurufen. Bei einem öffentlichen Repository sind damit auch die Anzeigentexte
öffentlich. Wer das nicht will, stellt das Repository auf privat; der Workflow
läuft dort genauso.

## Einrichtung

Schritt für Schritt in **[EINRICHTUNG.md](EINRICHTUNG.md)**, inklusive Übergabe
an Claude Code. Kurzfassung: Repo anlegen und pushen, Workflow-Permissions auf
*Read and write*, Pages-Source auf *GitHub Actions*, einmal von Hand starten.
Danach läuft er täglich um 05:40 UTC unter
`https://havock9000.github.io/jobradar/`.

Der Projektkontext für Claude Code steht in **[CLAUDE.md](CLAUDE.md)** —
Architektur, harte Grenzen, offene Aufgaben.

Lokal:

```bash
pip install -r requirements.txt
python -m jobradar.scan            # voller Lauf
python -m jobradar.scan --offline  # nur Dashboard neu bauen
python tests/test_offline.py       # Selbsttest ohne Netz
```

## Anpassen

Alles Änderbare steht in `config.yaml`:

- **`standort`** — Ankerpunkt und Umkreis.
- **`archetypen`** — Suchbegriffe und Gruppierung im Dashboard. Jeder Begriff
  wird einzeln abgefragt; kombinierte Begriffe liefern schlechtere Treffer als
  mehrere einzelne.
- **`screening`** — die Muster hinter den drei Statusfeldern. Reguläre Ausdrücke,
  Groß-/Kleinschreibung wird ignoriert.
- **`passung`** — die Aufgaben- und Reibungsmuster mit ihren Gewichten. Das
  ist der eigentliche Hebel, seit über den Text statt über den Titel
  entschieden wird.
- **`erreichbarkeit`** — Arbeitsmodell-Muster, Fahrzeitschwellen, Wochenbudget.
- **`ausschluss_titel`** — **entfernt seit dem 11.08.2026 nichts mehr.**
  `ausschluss_titel_hart: false` schaltet die Muster auf reine Abwertung
  (−2 im Score) mit sichtbarem Reibungsmarker. Grund: Der Filter hat
  nachweislich Passendes gekillt — ein „Performance Marketing Manager" 25 km
  entfernt mit „bis zu 100 % Remote" verschwand spurlos.
- **`seiten_quellen`** — Karriereseiten einzelner Arbeitgeber. Vor dem
  Eintragen prüfen, ob die Seite serverseitig rendert:

  ```bash
  python -m jobradar.seiten "https://beispiel.de/stellen"
  ```

  Meldet der Test viel HTML aber keine Treffer, lädt die Seite ihre Liste per
  JavaScript nach und ist so nicht auslesbar. Untersagt die robots.txt den
  Abruf, wird die Quelle im Lauf übersprungen und im Fuß des Dashboards genannt.
- **`rss_quellen`** — eigene service.bund.de-Feeds. Suche dort ausführen, dann
  über der Trefferliste *Suchergebnis als RSS-Feed* anklicken und die URL
  eintragen.

## Die drei Statusfelder

Jede Zeile trägt links drei Felder. Grün heißt unauffällig, gelb heißt
Einschränkung, rot heißt Ausschlusskriterium getroffen.

- **S — Studium.** Rot: Studium ohne genannte Alternative. Gelb: Studium *oder*
  vergleichbare Qualifikation. Grün: kein Studium im Text.
- **E — Ehrenamtslogik.** Rot, wenn der Text auf Vereins-, Verbands- oder
  Ehrenamtsbetreuung hinweist. Das ist der Marker für Durchsatz, der an
  Personen hängt, die nicht weisungsgebunden sind.
- **B — Befristung.**

Unter jeder Zeile steht die Textstelle, aus der der Status folgt. Das ist
Absicht: Mustererkennung produziert Fehlurteile, und ohne Belegstelle merkst du
das nicht.

## Bekannte Schwachstellen

- **Die BA-API ist inoffiziell.** Kein Rechtsanspruch, keine Versionszusage.
  Wenn Endpunkt oder Schlüssel wechseln, bricht der Lauf — dann in
  `bundesAPI/jobsuche-api` auf GitHub nachsehen.
- **Screening ist Textmustererkennung, keine Semantik.** "Studium wünschenswert"
  landet bei "hart", obwohl es weich gemeint ist. Belegstellen lesen.
- **Nicht jede Anzeige liefert einen Volltext.** Ohne Volltext wird nur der Titel
  gescreent, dann steht S/E/B auf grün, weil nichts gefunden wurde — nicht, weil
  nichts da ist.
- **Ohne JobPosting-Markup gibt es keinen Volltext.** Dann wird nur der Titel
  gescreent und die drei Statusfelder stehen fast immer auf grün. Solche Zeilen
  tragen im Dashboard den Hinweis *nur Titel* — grün heißt dort „nicht geprüft",
  nicht „unauffällig".
- **`details_folgen` kostet Anfragen.** Eine je Einzelanzeige. `max_details`
  deckelt das; bei Seiten mit vielen Anzeigen den Wert bewusst setzen.
- **Kleine Arbeitgeber melden nicht an die BA**, und viele moderne Karriereseiten
  rendern per JavaScript. Für Adressen, die keiner der drei Wege erreicht, bleibt
  manuelles Nachsehen nötig.
- **RSS von service.bund.de liefert wenig Struktur.** Arbeitgeber und Ort werden
  heuristisch aus dem Text gezogen und fehlen manchmal.

## Wie entschieden wird (seit 11.08.2026)

Bewertet wird der **Anzeigentext**, nicht die Berufsbezeichnung. Dieselbe
Tätigkeit heißt je nach Arbeitgeber „Referent*in Öffentlichkeitsarbeit",
„Sachbearbeitung Kommunikation", „Mitarbeiter*in Stabsstelle" oder
„Marketingassistenz" — ein Titelfilter entfernt darum zwangsläufig Passendes.

Der Score summiert getroffene Aufgabengruppen (Bewegtbild, Redaktion, Social,
Dokumentation, Rechte, Grafik) und zieht Reibungsmuster ab (CMS −1,
Ehrenamtslogik −3, Vertrieb −2, Titelmuster −2). Gewichte stehen unter
`passung` in `config.yaml`.

Nur drei Dinge entfernen eine Stelle aus der Standardansicht:

1. **Erreichbarkeit** — Fahrzeit gegen die Schwelle des Arbeitsmodells
   (onsite 45 min, unklar 60 min, hybrid 75 min, remote unbegrenzt) plus Wochenbudget
   (Präsenztage × Fahrzeit × 2 ≤ 450 min).
2. **Umfang** unter 20 Wochenstunden, wenn eine Stundenzahl im Text steht.
3. **Zwingendes Studium.** „Studium oder vergleichbare Qualifikation" bleibt.

Alles andere ist Markierung oder Punktabzug, und über „Ausgefilterte zeigen"
bleibt jede Entscheidung nachprüfbar.

### Fahrzeit

Mit `ORS_API_KEY` (openrouteservice.org, kostenlos) echte PKW-Fahrzeiten,
zwischengespeichert in `data/fahrzeiten.json`. Ohne Key wird geschätzt und im
Dashboard grau als geschätzt ausgewiesen. ORS liefert reine Autofahrzeit; bei
Bahnanbindung weicht der Tür-zu-Tür-Wert ab.

### Indeed und LinkedIn

`jobradar/jobspy_quelle.py` bindet python-jobspy ein, steht aber in
`config.yaml` auf `jobspy.aktiv: false`. Die Nutzungsbedingungen der Portale
untersagen automatisierten Zugriff — das Einschalten ist eine Entscheidung des
Betreibers, keine Voreinstellung. Dies ist keine Rechtsauskunft.

Technisch: **GitHub-Actions-IPs (Azure-Rechenzentren) werden von LinkedIn
zuverlässig geblockt.** Der LinkedIn-Teil bleibt dort ohne Wohn-Proxy leer —
das ist kein Bug. Proxys kommen über `JOBSPY_PROXIES` (kommasepariert) als
optionales Secret. Indeed/Deutschland liefert dagegen echte Volltexte
(geprüft: 8 von 8 Treffern, 1.789–6.816 Zeichen).

### academics.de

Bietet keinen RSS-Feed, und die robots.txt untersagt automatisierten Zugriff
ausdrücklich. Dort einen eigenen Suchagenten abonnieren — wie bei Interamt.
