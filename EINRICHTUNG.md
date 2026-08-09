# Einrichtung

Von Null bis zum ersten Lauf. Reihenfolge einhalten — Schritt 6 setzt Schritt 4
voraus, sonst scheitert der Workflow beim Commit.

## 1. Ordner anlegen

ZIP auspacken, dorthin wo du Projekte liegen hast.

```bash
cd ~/projekte/jobradar
```

## 2. Python-Umgebung

Python 3.11 oder neuer.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. Lokal testen, bevor irgendetwas online geht

```bash
python tests/test_offline.py
python tests/test_seiten.py
```

Beide müssen ohne Netz durchlaufen. Danach der erste echte Lauf:

```bash
python -m jobradar.scan
```

Die drei Quellen sind seit dem 09.08.2026 verifiziert und liefen durch. Wenn es
trotzdem scheitert, nicht selbst reparieren, sondern die Fehlerausgabe an Claude
Code geben (Schritt 7). Bei Erfolg entsteht `site/index.html`; im Browser öffnen
und ansehen, ob die Treffer inhaltlich taugen.

Erwarte wenige Treffer — rund ein Dutzend. Das ist kein Fehler: 50 Minuten
Pendelgrenze im ländlichen Raum plus enge Nische ergeben genau diesen Bestand.
Nachgemessen: ein größeres Zeitfenster (100 statt 30 Tage) bringt keinen
einzigen zusätzlichen Treffer.

## 4. GitHub-Repository

Repository anlegen — **privat** ist möglich, GitHub Pages funktioniert bei
privaten Repos allerdings nur mit bezahltem Plan.

### Was bei einem öffentlichen Repo sichtbar wird

Nach Pages geht ausschließlich `site/index.html` (siehe `path: ./site` im
Workflow). Im **Repository** liegen darüber hinaus offen:

- `config.yaml` — Wohn-PLZ, Pendelradius, Suchbegriffe, Screening-Kriterien
- `CLAUDE.md` — Beruf, Region, gesuchte Felder
- `data/jobs.json` — die gefundenen Stellen

Das ist bewusst so entschieden: Berufsbezeichnung, PLZ und Suchkriterien dürfen
öffentlich sein. Ein Lebenslauf steht nirgends.

**Was nicht öffentlich werden soll, steht in keiner Datei: deine Git-Identität.**
Jeder Commit trägt Name und E-Mail dauerhaft im Verlauf, und aus dem Verlauf
bekommt man sie praktisch nicht mehr heraus. Darum **vor dem ersten Commit**:

```bash
git init
```

```bash
git config user.name "jobradar"
```

```bash
git config user.email "10053725+Havock9000@users.noreply.github.com"
```

Die Adresse ist die Noreply-Adresse des Kontos `Havock9000` (die Zahl davor ist
die Konto-ID, sie gehört dazu). Sie steht auch unter *GitHub → Settings →
Emails*; dort sind zusätzlich **„Keep my email addresses private"** und **„Block
command line pushes that expose my email"** aktiviert — damit weist GitHub einen
Push zurück, der eine echte Adresse enthielte. Die täglichen Läufe sind
ohnehin sauber, der Workflow commitet als
`jobradar@users.noreply.github.com`.

Danach:

```bash
git add .
```

```bash
git commit -m "Jobradar"
```

```bash
git branch -M main
```

```bash
git remote add origin https://github.com/Havock9000/jobradar.git
```

```bash
git push -u origin main
```

## 5. Rechte für den Workflow

**Settings → Actions → General → Workflow permissions → "Read and write
permissions"** aktivieren. Ohne das kann der Workflow `data/jobs.json` nicht
zurückschreiben und bricht ab.

## 6. Pages aktivieren

**Settings → Pages → Source: "GitHub Actions".**

Dann **Actions → Jobradar → Run workflow**. Der erste Lauf dauert ein bis zwei
Minuten. Danach liegt das Dashboard unter

    https://havock9000.github.io/jobradar/

Ab jetzt läuft er täglich um 05:40 UTC von selbst.

## 7. Wenn der erste Lauf rot wird

Der Workflow ist der einzige Teil, der nie gelaufen ist. Die drei
wahrscheinlichsten Fehler, nach Häufigkeit:

- **`✗ ABBRUCH: Alle 36 BA-Abfragen fehlgeschlagen`** — die Bundesagentur weist
  die Runner-IP ab. GitHub-Runner stehen in Azure-Rechenzentren, deutsche
  Behörden-APIs sperren die regelmäßig. Von deinem Anschluss aus funktioniert
  die API nachweislich. Ausweg: den Lauf lokal per Windows-Aufgabenplanung
  ausführen und nur das Ergebnis pushen — der Workflow wird dann auf reines
  Deployment reduziert. Sag Bescheid, dann baue ich das um.
- **`Permission to … denied` beim Push** — Schritt 5 wurde nicht gespeichert.
  Zurück zu *Settings → Actions → General*, „Read and write permissions"
  auswählen und den **Save-Knopf direkt unter diesem Block** drücken.
- **`Get Pages site failed`** — Schritt 6 fehlt: *Settings → Pages → Source*
  muss auf „GitHub Actions" stehen, nicht auf „Deploy from a branch".

Ein Abbruch lässt `data/jobs.json` bewusst unverändert. Lieber ein alter
Bestand als ein Dashboard, das fälschlich „alles entfernt" meldet.

## 7. Übergabe an Claude Code

Im Projektordner:

```bash
claude
```

`CLAUDE.md` wird automatisch gelesen und enthält Architektur, Grenzen und die
Aufgabenliste. Als Einstieg reicht:

> Führ den ersten echten Lauf durch und berichte, was von den drei Quellen
> tatsächlich funktioniert.

Drei Punkte, die im weiteren Verlauf wichtig werden:

- **Erst laufen lassen, dann ändern.** Die Fehlerbilder in `CLAUDE.md` sind
  Vermutungen. Was der echte Lauf zeigt, sticht sie.
- **`config.yaml` gehört dir.** Suchbegriffe bilden deine Suchstrategie ab, nicht
  nur Suchtechnik. Wenn Claude Code sie ändern will, soll es fragen — das steht
  so in `CLAUDE.md`.
- **Die Grenze zu LinkedIn ist dokumentiert.** Falls das Thema wiederkommt, steht
  die Begründung im README und in `CLAUDE.md`, damit nicht jedes Mal neu
  verhandelt wird.
