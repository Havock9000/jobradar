"""Rendert data/jobs.json zu einem statischen Dashboard (index.html)."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobradar.lauf import sortierschluessel

CSS = """
:root{
  --stein:#e9e7e0; --stein-tief:#dbd8cf; --papier:#f5f4f0;
  --tinte:#1b2018; --tinte-weich:#5c6355;
  --moos:#40603c; --moos-hell:#6f8f63;
  --bernstein:#a86a10; --ton:#9c4a2f;
  --linie:#c9c6bb;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--stein); color:var(--tinte);
  font-family:"Source Sans 3","Segoe UI",system-ui,sans-serif;
  font-size:16px; line-height:1.55;
}
a{color:var(--moos)}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}

/* Kopf */
header{border-bottom:3px solid var(--tinte);padding-bottom:18px;margin-bottom:8px}
.eyebrow{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:11px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--tinte-weich);margin:0 0 6px
}
h1{
  font-family:"Archivo","Arial Narrow",sans-serif;
  font-weight:700;font-size:clamp(30px,6vw,46px);
  letter-spacing:-.02em;line-height:1.02;margin:0
}
.lauf{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:12px;
  color:var(--tinte-weich);margin-top:10px
}
.lauf b{color:var(--tinte);font-weight:600}

/* Legende der Statusspalte – das ist der Kern des Boards */
.legende{
  display:flex;flex-wrap:wrap;gap:18px;
  padding:14px 0 18px;border-bottom:1px solid var(--linie);
  font-size:13px;color:var(--tinte-weich)
}
.legende span{display:flex;align-items:center;gap:7px}

/* Filter */
.filter{display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 26px}
.filter button{
  font:inherit;font-size:13px;padding:6px 13px;cursor:pointer;
  background:transparent;border:1px solid var(--linie);border-radius:999px;
  color:var(--tinte-weich);transition:none
}
.filter button:hover{border-color:var(--tinte-weich)}
.filter button[aria-pressed="true"]{
  background:var(--tinte);border-color:var(--tinte);color:var(--papier)
}
.filter button:focus-visible{outline:2px solid var(--moos);outline-offset:2px}

/* Gruppen */
.gruppe{margin-bottom:44px}
.gruppe h2{
  font-family:"Archivo",sans-serif;font-weight:600;font-size:19px;
  letter-spacing:-.01em;margin:0 0 2px;
  display:flex;align-items:baseline;gap:10px
}
.zaehler{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:12px;
  color:var(--tinte-weich);font-weight:400
}
.notiz{font-size:14px;color:var(--tinte-weich);margin:0 0 14px;max-width:62ch}

/* Zeile */
.stelle{
  display:grid;grid-template-columns:96px 1fr auto;gap:16px;align-items:start;
  padding:15px 0;border-top:1px solid var(--linie)
}
.stelle:last-child{border-bottom:1px solid var(--linie)}
.stelle.entfernt{opacity:.42}

/* Signaturelement: drei Statusfelder, links, immer gleich positioniert */
.ampel{display:flex;flex-wrap:wrap;gap:4px;padding-top:4px;align-items:center}
.slot{
  width:18px;height:18px;border-radius:3px;
  border:1px solid var(--linie);background:var(--papier);
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:10px;font-weight:600;
  display:flex;align-items:center;justify-content:center;color:var(--tinte-weich)
}
.slot.warn{background:#f0dfae;border-color:var(--bernstein);color:#6b4308}
.slot.stop{background:#e8cdc2;border-color:var(--ton);color:#7a3320}
.slot.gut{background:#d5e2cd;border-color:var(--moos);color:#2c4429}

.titel{font-weight:600;font-size:16.5px;line-height:1.3;margin:0 0 3px}
.titel a{text-decoration:none;color:var(--tinte);border-bottom:1.5px solid var(--moos-hell)}
.titel a:hover{border-bottom-color:var(--tinte)}
.meta{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:12px;
  color:var(--tinte-weich);display:flex;flex-wrap:wrap;gap:4px 12px
}
.belege{margin:8px 0 0;padding:0;list-style:none}
.belege li{
  font-size:12.5px;color:var(--tinte-weich);line-height:1.45;
  padding-left:14px;position:relative;margin-top:3px
}
.belege li::before{
  content:"";position:absolute;left:0;top:8px;
  width:6px;height:1px;background:var(--tinte-weich)
}
.rechts{text-align:right;white-space:nowrap;padding-top:3px}
.frist{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:11.5px;
  color:var(--ton);font-weight:600;display:block;margin-top:4px
}
.frist.ruhig{color:var(--tinte-weich);font-weight:400}
.stelle.abgelaufen{opacity:.38}
.nurtitel{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:10.5px;
  color:var(--tinte-weich);border:1px dashed var(--linie);
  padding:1px 5px;border-radius:2px;margin-left:6px;white-space:nowrap
}
.neu{
  display:inline-block;font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  background:var(--bernstein);color:var(--papier);
  padding:2px 7px;border-radius:2px
}
.datum{font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:12px;color:var(--tinte-weich);display:block;margin-top:5px}

.leer{
  padding:40px 0;color:var(--tinte-weich);font-size:15px;
  border-top:1px solid var(--linie)
}
footer{
  margin-top:56px;padding-top:18px;border-top:1px solid var(--linie);
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;font-size:11.5px;
  color:var(--tinte-weich);line-height:1.7
}

@media (max-width:620px){
  .stelle{grid-template-columns:1fr;gap:8px}
  .rechts{grid-column:1;text-align:left;padding-top:0}
  .datum{display:inline;margin-left:10px}
  .ampel{flex-direction:row}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
.score{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:15px;font-weight:600;min-width:2.4em;text-align:right;display:inline-block
}
.score.hoch{color:var(--moos)}
.score.mittel{color:var(--bernstein)}
.score.tief{color:var(--tinte-weich)}
.score.leer{color:var(--tinte-weich);font-weight:400}
.marker{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:10px;letter-spacing:.05em;text-transform:uppercase;
  padding:1px 5px;border-radius:2px;margin-right:4px;white-space:nowrap;
  border:1px solid var(--linie)
}
.marker.auf{background:var(--moos);color:var(--papier);border-color:var(--moos)}
.marker.rei{background:transparent;color:var(--tinte-weich);border-style:dashed}
.modell{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  padding:1px 5px;border-radius:2px;margin-right:5px;border:1px solid currentColor
}
.geschaetzt{color:var(--tinte-weich)}
.gefiltert{opacity:.55}
.gefiltert .titel a{text-decoration:line-through}
.grundmarke{
  font-family:"IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,"DejaVu Sans Mono",monospace;
  font-size:10px;text-transform:uppercase;letter-spacing:.06em;
  background:var(--linie);padding:1px 5px;border-radius:2px;margin-right:5px
}
.auchbei{font-size:11.5px;color:var(--tinte-weich)}
"""

JS = """
(function(){
  var filter = {archetyp:'alle', nurNeu:false, ohneEhrenamt:false,
                ohneAbgelaufen:true, zeigeGefiltert:false, nurMitText:false};
  var sortierung = 'score';

  function zahl(el, name){
    var v = el.dataset[name];
    return (v === '' || v === undefined) ? null : Number(v);
  }

  function anwenden(){
    document.querySelectorAll('.stelle').forEach(function(el){
      var zeig = true;
      if (filter.archetyp !== 'alle' && el.dataset.archetyp !== filter.archetyp) zeig = false;
      if (filter.nurNeu && el.dataset.neu !== '1') zeig = false;
      if (filter.ohneEhrenamt && el.dataset.ehrenamt === '1') zeig = false;
      if (filter.ohneAbgelaufen && el.dataset.abgelaufen === '1') zeig = false;
      if (filter.nurMitText && el.dataset.text !== '1') zeig = false;
      // Ausgefilterte sind vorhanden, nur ausgeblendet — damit pruefbar
      // bleibt, ob ein Filtermuster zu breit greift.
      if (!filter.zeigeGefiltert && el.dataset.gefiltert !== '') zeig = false;
      el.hidden = !zeig;
    });

    document.querySelectorAll('.gruppe').forEach(function(g){
      var sichtbare = Array.prototype.slice.call(
        g.querySelectorAll('.stelle:not([hidden])'));
      sichtbare.sort(function(a, b){
        if (sortierung === 'fahrzeit'){
          var fa = zahl(a,'fahrzeit'), fb = zahl(b,'fahrzeit');
          if (fa === null && fb === null) return 0;
          if (fa === null) return 1;
          if (fb === null) return -1;
          return fa - fb;
        }
        if (sortierung === 'datum'){
          return (b.dataset.datum || '').localeCompare(a.dataset.datum || '');
        }
        var sa = zahl(a,'score'), sb = zahl(b,'score');
        if (sa === null && sb === null) return 0;
        if (sa === null) return 1;
        if (sb === null) return -1;
        return sb - sa;
      });
      sichtbare.forEach(function(el){ g.appendChild(el); });
      g.hidden = sichtbare.length === 0;
      var z = g.querySelector('.zaehler');
      if (z) z.textContent = sichtbare.length + ' sichtbar';
    });

    var alle = document.querySelectorAll('.stelle:not([hidden])').length;
    var leer = document.getElementById('leer');
    if (leer) leer.hidden = alle > 0;
  }

  document.querySelectorAll('[data-filter]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var art = btn.dataset.filter, wert = btn.dataset.wert;
      if (art === 'archetyp'){
        filter.archetyp = wert;
        document.querySelectorAll('[data-filter="archetyp"]').forEach(function(b){
          b.setAttribute('aria-pressed', String(b.dataset.wert === wert));
        });
      } else {
        filter[art] = !filter[art];
        btn.setAttribute('aria-pressed', String(filter[art]));
      }
      anwenden();
    });
  });

  document.querySelectorAll('[data-sort]').forEach(function(btn){
    btn.addEventListener('click', function(){
      sortierung = btn.dataset.sort;
      document.querySelectorAll('[data-sort]').forEach(function(b){
        b.setAttribute('aria-pressed', String(b.dataset.sort === sortierung));
      });
      anwenden();
    });
  });

  anwenden();
})();
"""


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _tage_bis(iso_datum: str | None) -> int | None:
    if not iso_datum:
        return None
    try:
        ziel = datetime.strptime(iso_datum, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (ziel - datetime.now(timezone.utc)).days


def _ampel(screening: dict[str, Any]) -> tuple[str, str, str]:
    """Drei Statusfelder: Studium / Ehrenamtslogik / Befristung."""
    stufe = (screening.get("studium") or {}).get("stufe", "offen")
    if stufe == "hart":
        studium = '<span class="slot stop" title="Studium zwingend">S</span>'
    elif stufe == "weich":
        studium = '<span class="slot warn" title="Studium oder vergleichbare Qualifikation">S</span>'
    else:
        studium = '<span class="slot gut" title="Kein Studium gefordert">S</span>'

    if (screening.get("ehrenamtslogik") or {}).get("getroffen"):
        ehrenamt = '<span class="slot stop" title="Ehrenamtslogik erkannt">E</span>'
    else:
        ehrenamt = '<span class="slot gut" title="Keine Ehrenamtslogik erkannt">E</span>'

    if (screening.get("befristung") or {}).get("getroffen"):
        befristung = '<span class="slot warn" title="Befristet">B</span>'
    else:
        befristung = '<span class="slot gut" title="Keine Befristung erkennbar">B</span>'

    return studium, ehrenamt, befristung


def _belege(stelle: dict[str, Any]) -> str:
    """Jedes Urteil zeigt die Textstelle, aus der es folgt."""
    screening = stelle.get("screening") or {}
    zeilen: list[str] = []

    modell = stelle.get("arbeitsmodell") or {}
    if modell.get("beleg"):
        zeilen.append(f"Arbeitsmodell ({modell.get('modell')}): {modell['beleg']}")

    erreichbar = stelle.get("erreichbar") or {}
    if erreichbar.get("hinweis"):
        zeilen.append(f"Erreichbarkeit: {erreichbar['hinweis']}")

    studium = screening.get("studium") or {}
    if studium.get("beleg"):
        praefix = ("Studium zwingend" if studium.get("stufe") == "hart"
                   else "Studium mit Alternative")
        zeilen.append(f"{praefix}: {studium['beleg']}")
    ehrenamt = screening.get("ehrenamtslogik") or {}
    if ehrenamt.get("beleg"):
        zeilen.append(f"Ehrenamtslogik: {ehrenamt['beleg']}")
    befristung = screening.get("befristung") or {}
    if befristung.get("beleg"):
        zeilen.append(f"Befristung: {befristung['beleg']}")

    for r in (stelle.get("passung") or {}).get("reibung") or []:
        zeilen.append(f"Reibung {r.get('gruppe')} ({r.get('gewicht')}): "
                      f"{r.get('beleg')}")

    if not zeilen:
        return ""
    items = "".join(f"<li>{esc(z)}</li>" for z in zeilen)
    return f'<ul class="belege">{items}</ul>'


MODELL_TITEL = {
    "remote": "Vollständig remote laut Anzeigentext",
    "hybrid": "Teilweise vor Ort",
    "onsite": "Präsenz erwartet",
    "unklar": "Arbeitsmodell nicht angegeben — gegen die Hybrid-Schwelle geprüft",
}


def _zeile(stelle: dict[str, Any]) -> str:
    screening = stelle.get("screening") or {}
    s, e, b = _ampel(screening)
    stufe = (screening.get("studium") or {}).get("stufe", "offen")
    ehrenamt = "1" if (screening.get("ehrenamtslogik") or {}).get("getroffen") else "0"

    passung = stelle.get("passung") or {}
    score = passung.get("score")
    hat_text = passung.get("status") == "bewertet"
    if not hat_text:
        score_html = ('<span class="score leer" title="Keine Beschreibung '
                      'vorhanden — kein Score, kein Urteil">–</span>')
    else:
        klasse = "hoch" if score >= 5 else ("mittel" if score >= 2 else "tief")
        score_html = (f'<span class="score {klasse}" title="Summe der '
                      f'getroffenen Aufgabengruppen minus Reibung">{score:+d}</span>')

    marker = "".join(
        f'<span class="marker auf">{esc(a)}</span>'
        for a in passung.get("aufgaben") or [])
    marker += "".join(
        f'<span class="marker rei" title="{esc(r.get("beleg"))}">'
        f'{esc(r.get("gruppe"))} {esc(r.get("gewicht"))}</span>'
        for r in passung.get("reibung") or [])

    meta: list[str] = []
    modell = (stelle.get("arbeitsmodell") or {}).get("modell", "unklar")
    meta.append(f'<span class="modell" title="{esc(MODELL_TITEL.get(modell, ""))}">'
                f'{esc(modell)}</span>')

    fahrzeit = stelle.get("fahrzeit") or {}
    minuten = fahrzeit.get("minuten")
    if minuten is not None:
        klasse = "geschaetzt" if fahrzeit.get("geschaetzt") else ""
        titel = ("geschätzt über " + str(fahrzeit.get("quelle"))
                 if fahrzeit.get("geschaetzt") else "OpenRouteService, PKW")
        meta.append(f'<span class="{klasse}" title="{esc(titel)}">'
                    f'{int(minuten)} min</span>')
    else:
        meta.append('<span class="geschaetzt" title="Weder ORS noch eine '
                    'Entfernungsangabe der Quelle">Fahrzeit unbekannt</span>')

    if stelle.get("arbeitgeber"):
        meta.append(esc(stelle["arbeitgeber"]))
    if stelle.get("ort"):
        meta.append(esc(stelle["ort"]))
    if stelle.get("entgelt"):
        meta.append(esc(stelle["entgelt"]))
    if stelle.get("wochenstunden"):
        meta.append(esc(f"{stelle['wochenstunden']:g} h/Woche"))
    meta.append(esc(stelle.get("quelle", "")))
    if stelle.get("entfernt"):
        meta.append("nicht mehr gelistet")

    auch = stelle.get("auch_gefunden_bei") or []
    if auch:
        quellen = ", ".join(sorted({a.get("quelle", "") for a in auch if a.get("quelle")}))
        meta.append(f'<span class="auchbei">auch bei {esc(quellen)}</span>')

    grund = stelle.get("gefiltert")
    grund_html = ""
    if grund:
        grund_html = f'<span class="grundmarke">{esc(grund)}</span>'

    frist = stelle.get("frist")
    tage = _tage_bis(frist)
    abgelaufen = tage is not None and tage < 0
    datum = esc(stelle.get("veroeffentlicht") or "")
    neu_badge = ('<span class="neu">neu</span>'
                 if stelle.get("neu") and not abgelaufen else "")

    frist_html = ""
    if frist:
        if abgelaufen:
            frist_html = f'<span class="frist">Frist abgelaufen ({esc(frist)})</span>'
        elif tage is not None and tage <= 10:
            frist_html = f'<span class="frist">Frist {esc(frist)} — noch {tage} Tage</span>'
        else:
            frist_html = f'<span class="frist ruhig">Frist {esc(frist)}</span>'

    nur_titel = ('<span class="nurtitel" title="Keine Beschreibung vorhanden — '
                 'Status und Score sind hier nicht belastbar">ohne Beschreibung</span>'
                 if not hat_text else "")

    klassen = "stelle" + (" gefiltert" if grund else "")
    return f"""<article class="{klassen}" data-archetyp="{esc(stelle.get('archetyp'))}"
  data-neu="{'1' if stelle.get('neu') else '0'}" data-studium="{esc(stufe)}"
  data-ehrenamt="{ehrenamt}" data-abgelaufen="{'1' if abgelaufen else '0'}"
  data-gefiltert="{esc(grund or '')}" data-text="{'1' if hat_text else '0'}"
  data-score="{score if hat_text else ''}"
  data-fahrzeit="{minuten if minuten is not None else ''}"
  data-datum="{datum}">
  <div class="ampel">{score_html}{s}{e}{b}</div>
  <div>
    <p class="titel">{grund_html}<a href="{esc(stelle.get('url'))}" target="_blank" rel="noopener">{esc(stelle.get('titel') or 'Ohne Titel')}</a>{nur_titel}</p>
    <div class="meta">{''.join(f'<span>{m}</span>' for m in meta if m)}</div>
    <div class="meta">{marker}</div>
    {_belege(stelle)}
  </div>
  <div class="rechts">{neu_badge}<span class="datum">{datum}</span>{frist_html}</div>
</article>"""


def baue_dashboard(cfg: dict[str, Any], zustand: dict[str, Any], ziel: Path) -> Path:
    archetypen = sorted(cfg.get("archetypen", []), key=lambda a: a.get("rang", 99))
    stellen = list(zustand.get("stellen", {}).values())

    # Serverseitige Vorsortierung nach Score; die Filterleiste kann im Browser
    # auf Fahrzeit oder Datum umschalten.
    stellen.sort(key=lambda s: s.get("veroeffentlicht") or "0000-00-00", reverse=True)
    stellen.sort(key=sortierschluessel)

    gruppen_html = []
    for a in archetypen:
        eintraege = [s for s in stellen if s.get("archetyp") == a["id"]]
        if not eintraege:
            continue
        zeilen = "".join(_zeile(s) for s in eintraege)
        notiz = f'<p class="notiz">{esc(a.get("notiz"))}</p>' if a.get("notiz") else ""
        sichtbar = sum(1 for s in eintraege if not s.get("gefiltert"))
        gruppen_html.append(f"""<section class="gruppe" data-archetyp="{esc(a['id'])}">
  <h2>{esc(a['label'])} <span class="zaehler">{sichtbar} sichtbar</span></h2>
  {notiz}
  {zeilen}
</section>""")

    # Eintraege aus dem Bestand, deren Archetyp es nicht mehr gibt (nach einer
    # Umbenennung in config.yaml), duerfen nicht stillschweigend verschwinden.
    bekannte_ids = {a["id"] for a in archetypen}
    reste = [s for s in stellen if s.get("archetyp") not in bekannte_ids]
    if reste:
        zeilen = "".join(_zeile(s) for s in reste)
        sichtbar = sum(1 for s in reste if not s.get("gefiltert"))
        gruppen_html.append(f"""<section class="gruppe" data-archetyp="_rest">
  <h2>Ohne aktuellen Archetyp <span class="zaehler">{sichtbar} sichtbar</span></h2>
  <p class="notiz">Diese Anzeigen stammen aus einem Lauf mit anderer
  Archetyp-Einteilung. Beim naechsten Lauf werden sie neu zugeordnet oder
  verfallen.</p>
  {zeilen}
</section>""")

    laeufe = zustand.get("laeufe", [])
    letzter = laeufe[-1] if laeufe else {}
    stand = datetime.now(timezone.utc).strftime("%d.%m.%Y, %H:%M UTC")

    uebersprungen = letzter.get("uebersprungen") or []
    uebersprungen_html = ""
    if uebersprungen:
        zeilen = "".join(f"<br>· {esc(u)}" for u in uebersprungen)
        uebersprungen_html = f"Beim letzten Lauf übersprungen:{zeilen}<br>"

    gefiltert = letzter.get("gefiltert") or {}
    gefiltert_text = ", ".join(
        f"{esc(grund)} {esc(zahl)}" for grund, zahl in gefiltert.items()) or "keine"

    filter_buttons = ['<button data-filter="archetyp" data-wert="alle" aria-pressed="true">Alle Felder</button>']
    for a in archetypen:
        filter_buttons.append(
            f'<button data-filter="archetyp" data-wert="{esc(a["id"])}" '
            f'aria-pressed="false">{esc(a["label"])}</button>')
    filter_buttons += [
        '<button data-filter="nurNeu" aria-pressed="false">Nur neue</button>',
        '<button data-filter="ohneEhrenamt" aria-pressed="false">Ehrenamtslogik ausblenden</button>',
        '<button data-filter="ohneAbgelaufen" aria-pressed="true">Abgelaufene ausblenden</button>',
        '<button data-filter="nurMitText" aria-pressed="false">Nur mit Beschreibung</button>',
        '<button data-filter="zeigeGefiltert" aria-pressed="false">Ausgefilterte zeigen</button>',
    ]
    sort_buttons = [
        '<button data-sort="score" aria-pressed="true">Score</button>',
        '<button data-sort="fahrzeit" aria-pressed="false">Fahrzeit</button>',
        '<button data-sort="datum" aria-pressed="false">Datum</button>',
    ]

    doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jobradar</title>
<!-- Bewusst keine Web-Fonts. Ein <link> auf fonts.googleapis.com meldet bei
     jedem Oeffnen IP, Browser und aufgerufene Seite an Google — bei einer
     Seite, die die eigene Stellensuche abbildet, ist das die eine Information,
     die niemand mitlesen soll. -->
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <p class="eyebrow">Stellenradar · {esc(cfg['standort'].get('ort') or cfg['standort']['wo'])}</p>
  <h1>Was gerade offen ist</h1>
  <p class="lauf">Stand {esc(stand)} · <b>{esc(letzter.get('sichtbar', 0))}</b> in der Standardansicht · <b>{esc(letzter.get('gesamt', 0))}</b> im Bestand · <b>{esc(letzter.get('neu', 0))}</b> neu</p>
</header>

<div class="legende">
  <span><span class="score hoch">+5</span> Score aus dem Anzeigentext, nicht aus dem Titel</span>
  <span><span class="slot gut">S</span> Studium: kein / mit Alternative / zwingend</span>
  <span><span class="slot stop">E</span> Ehrenamtslogik erkannt</span>
  <span><span class="slot warn">B</span> Befristet</span>
  <span><span class="nurtitel">ohne Beschreibung</span> kein Score — Datenlage fehlt</span>
</div>

<div class="filter">{''.join(filter_buttons)}</div>
<div class="filter">Sortierung: {''.join(sort_buttons)}</div>

{''.join(gruppen_html) if gruppen_html else ''}
<p class="leer" id="leer">Keine Anzeigen passen zu den gewählten Filtern.</p>

<footer>
Bewertet wird der <b>Anzeigentext</b>, nicht die Berufsbezeichnung. Dieselbe Tätigkeit heißt je nach Arbeitgeber „Referent*in Öffentlichkeitsarbeit“, „Sachbearbeitung Kommunikation“ oder „Marketingassistenz“ — ein Titelfilter entfernt darum zwangsläufig Passendes. Der Score summiert getroffene Aufgabengruppen und zieht Reibungsmuster ab.<br>
Entfernt werden nur drei Dinge: zu lange Fahrzeit, Umfang unter {esc((cfg.get('harte_filter') or {}).get('mindest_wochenstunden', 20))} Wochenstunden und zwingend gefordertes Studium. Beim letzten Lauf ausgefiltert: {gefiltert_text}. Über „Ausgefilterte zeigen“ nachprüfbar.<br>
Fahrzeiten sind PKW-Zeiten. Ohne <code>ORS_API_KEY</code> werden sie geschätzt und grau dargestellt; bei guter Bahnanbindung weicht der Tür-zu-Tür-Wert ab.<br>
{esc(letzter.get('zusammengefuehrt', 0))} Duplikate zusammengeführt (der Eintrag mit der längeren Beschreibung gewinnt, die anderen Fundstellen stehen als „auch bei“ dabei). {esc(letzter.get('ohne_beschreibung', 0))} Anzeigen ohne Beschreibung — die bekommen keinen Score, weil eine 0 ein Urteil wäre, das die Datenlage nicht hergibt.<br>
{uebersprungen_html}Quellen: Bundesagentur für Arbeit (inoffizielle Jobsuche-API), service.bund.de (RSS), einzelne Karriereseiten nach robots.txt-Prüfung, optional JobSpy. Die Statusfelder sind Mustererkennung, keine Rechtsauskunft — Belegstellen stehen unter jeder Zeile.
</footer>
</div>
<script>{JS}</script>
</body>
</html>"""

    ziel.write_text(doc, encoding="utf-8")
    return ziel


if __name__ == "__main__":
    import sys
    import yaml

    root = Path(__file__).resolve().parent.parent
    cfg = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    zustand = json.loads((root / "data" / "jobs.json").read_text(encoding="utf-8"))
    print(baue_dashboard(cfg, zustand, root / "site" / "index.html"), file=sys.stderr)
