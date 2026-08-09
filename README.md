# Jobradar

Fragt täglich zwei öffentliche Quellen nach Stellenanzeigen im Umkreis ab, screent
den Anzeigentext gegen die eigenen Ausschlusskriterien und veröffentlicht das
Ergebnis als statische Seite.

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

## Was bewusst nicht abgefragt wird

LinkedIn, Indeed und StepStone untersagen automatisierten Zugriff in ihren
Nutzungsbedingungen. Ein eigens dafür angelegtes Konto verletzt diese
Bedingungen und riskiert die Sperrung — mitten in einer Bewerbungsphase ein
teurer Preis für Daten, die die BA-Quelle weitgehend mit abdeckt. Dasselbe gilt
für alles hinter einem Login und für Portale mit kostenpflichtigem Zugang
(z. B. WILA Arbeitsmarkt); die dort abonnierte Ausgabe ist der vorgesehene Weg.

Das Modul `jobradar/seiten.py` bewegt sich bewusst innerhalb dieser Grenze:
nur öffentliche Seiten ohne Login, robots.txt vor jedem Abruf geprüft,
sprechender User-Agent, eine Anfrage pro Seite und Lauf, gespeichert werden nur
Titel und Link.

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
- **`ausschluss_titel`** — Rollen, die gar nicht erst auftauchen sollen
  (Performance Marketing, reine Social-Media- und Vertriebsrollen). Wird
  **nur gegen den Titel** geprüft, damit Anzeigen mit Social Media als einer
  Aufgabe unter vielen erhalten bleiben. Die Zahl der ausgeschlossenen Anzeigen
  steht im Fuß des Dashboards — steigt sie auffällig, ist ein Muster zu breit.
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
