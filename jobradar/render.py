"""Rendert data/jobs.json zu einem statischen Dashboard (site/index.html).

Aufbau seit dem 31.08.2026:

  * Links die Liste, rechts eine Karte. Die Karte ist KEINE Straßenkarte,
    sondern ein Radialdiagramm: Hamm (Sieg) in der Mitte, Ringe bei 30/45/60/75
    Fahrminuten, jede Stelle als Punkt in ihrer echten Himmelsrichtung.
    Begründung steht bei `KARTE_HINWEIS` weiter unten.
  * Jede Zeile zeigt nur, was zum Sortieren und Aussortieren nötig ist.
    Belegstellen, Entgelt, Wochenstunden und Quelle stehen im aufklappbaren
    Teil — sie sind wichtig, aber nicht beim Überfliegen.

Weiterhin gilt: keine Web-Fonts, kein CDN, keine Kartenkacheln. Die Seite
macht null Fremdaufrufe.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jobradar.lauf import sortierschluessel

# Warum kein Leaflet mit OSM-Kacheln: Kacheln kommen von einem fremden Server
# und melden bei jedem Öffnen IP und Kartenausschnitt dorthin. Bei einer Seite,
# die die laufende Stellensuche abbildet, ist das die eine Information, die
# niemand mitlesen soll — dieselbe Begründung, aus der die Google Fonts
# geflogen sind. Das Radialdiagramm beantwortet die eigentliche Frage ohnehin
# direkter: nicht "welche Straße", sondern "wie weit und in welche Richtung".
KARTE_HINWEIS = ("Kein Straßennetz, sondern Fahrzeit und Himmelsrichtung: "
                 "Mitte ist Hamm (Sieg), die Ringe liegen bei 30, 45, 60 und "
                 "75 Fahrminuten. Keine Kartenkacheln, keine Fremdaufrufe.")

CSS = """
:root{
  --grund:#14171c; --flaeche:#1b1f26; --flaeche-hoch:#222831;
  --linie:#2c333d; --linie-hell:#3a434f;
  --text:#e6e9ee; --text-weich:#9aa4b2; --text-schwach:#6b7686;
  --gut:#5ec27a; --mittel:#e0b341; --stop:#e0705f; --akzent:#7aa2f7;
  --remote:#5ec27a; --hybrid:#7aa2f7; --onsite:#e0705f; --unklar:#6b7686;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;background:var(--grund);color:var(--text);
  font-family:"Segoe UI",system-ui,-apple-system,sans-serif;
  font-size:15px;line-height:1.5;
}
a{color:var(--akzent)}
.wrap{max-width:1500px;margin:0 auto;padding:22px 20px 70px}

header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 20px;margin-bottom:6px}
h1{font-size:21px;font-weight:600;letter-spacing:-.01em;margin:0}
.stand{font-size:12.5px;color:var(--text-schwach);font-variant-numeric:tabular-nums}
.kennzahlen{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0 18px}
.kennzahl{background:var(--flaeche);border:1px solid var(--linie);
  border-radius:9px;padding:9px 14px;min-width:104px}
.kennzahl b{display:block;font-size:21px;font-weight:600;line-height:1.15;
  font-variant-numeric:tabular-nums}
.kennzahl span{font-size:11px;color:var(--text-schwach);
  text-transform:uppercase;letter-spacing:.06em}

.leiste{display:flex;flex-wrap:wrap;gap:16px;align-items:center;
  padding:12px 0 16px;border-top:1px solid var(--linie);
  border-bottom:1px solid var(--linie);margin-bottom:20px}
.leiste .satz{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.leiste .kopf{font-size:11px;color:var(--text-schwach);
  text-transform:uppercase;letter-spacing:.07em;margin-right:2px}
button{
  font:inherit;font-size:12.5px;padding:5px 11px;cursor:pointer;
  background:var(--flaeche);border:1px solid var(--linie);border-radius:7px;
  color:var(--text-weich)
}
button:hover{border-color:var(--linie-hell);color:var(--text)}
button[aria-pressed="true"]{background:var(--akzent);border-color:var(--akzent);
  color:#10141a;font-weight:600}
button:focus-visible{outline:2px solid var(--akzent);outline-offset:2px}

.spalten{display:grid;grid-template-columns:1fr 420px;gap:26px;align-items:start}
@media (max-width:1080px){.spalten{grid-template-columns:1fr}}

/* Karte */
.kartenfeld{position:sticky;top:16px;background:var(--flaeche);
  border:1px solid var(--linie);border-radius:12px;padding:14px}
.kartenfeld h2{font-size:13px;margin:0 0 2px;font-weight:600}
.kartenfeld p{font-size:11.5px;color:var(--text-schwach);margin:0 0 10px;
  line-height:1.45}
#karte{width:100%;height:auto;display:block;touch-action:manipulation}
#karte circle.punkt{cursor:pointer;transition:none}
#karte circle.punkt:hover,#karte circle.punkt.aktiv{stroke:#fff;stroke-width:2}
.ring{fill:none;stroke:var(--linie-hell);stroke-dasharray:3 4}
.ringtext{fill:var(--text-schwach);font-size:9px;
  font-family:ui-monospace,Consolas,monospace}
.anker{fill:var(--text);stroke:var(--grund);stroke-width:2}
.ankertext{fill:var(--text-weich);font-size:10px}
.legende{display:flex;flex-wrap:wrap;gap:5px 12px;margin-top:10px;
  font-size:11.5px;color:var(--text-weich)}
.legende span{display:flex;align-items:center;gap:6px;cursor:help}
.punktprobe{width:10px;height:10px;border-radius:50%;flex:0 0 auto}
#tooltip{position:fixed;pointer-events:none;z-index:50;max-width:280px;
  background:var(--flaeche-hoch);border:1px solid var(--linie-hell);
  border-radius:8px;padding:8px 10px;font-size:12px;line-height:1.4;
  box-shadow:0 6px 22px rgba(0,0,0,.45);display:none}
#tooltip b{display:block;margin-bottom:3px}
#tooltip em{color:var(--text-schwach);font-style:normal;font-size:11px}
.ohneort{font-size:11.5px;color:var(--text-schwach);margin-top:10px}

/* Bestenfeld: die staerksten Treffer quer ueber alle Kategorien */
.besten{background:var(--flaeche);border:1px solid var(--linie);
  border-radius:12px;padding:14px 16px;margin-bottom:22px}
.besten h2{font-size:14px;margin:0 0 3px;font-weight:600}
.besten .unterzeile{font-size:11.5px;color:var(--text-schwach);margin:0 0 12px}
.bestenspalten{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media (max-width:760px){.bestenspalten{grid-template-columns:1fr}}
.bestenspalte h3{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--text-schwach);margin:0 0 7px;display:flex;align-items:center;gap:6px}
.bestenliste{list-style:none;margin:0;padding:0}
.bestenliste li{display:grid;grid-template-columns:32px 1fr auto;gap:9px;
  align-items:baseline;padding:5px 6px;border-radius:6px;cursor:pointer}
.bestenliste li:hover{background:var(--flaeche-hoch)}
.bestenliste .bs{font-weight:600;text-align:right;font-variant-numeric:tabular-nums}
.bestenliste .bt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bestenliste .bm{font-size:11.5px;color:var(--text-schwach);
  font-variant-numeric:tabular-nums;white-space:nowrap}
.bestenliste .leerzeile{color:var(--text-schwach);font-size:12px;
  grid-column:1/-1;padding:3px 0}

/* Gruppen und Zeilen */
.gruppe{margin-bottom:26px}
.gruppe h2{font-size:14px;font-weight:600;margin:0 0 8px;
  display:flex;align-items:baseline;gap:9px}
.zaehler{font-size:11.5px;color:var(--text-schwach);font-weight:400;
  font-variant-numeric:tabular-nums}

.stelle{background:var(--flaeche);border:1px solid var(--linie);
  border-radius:10px;padding:11px 13px;margin-bottom:7px}
.stelle:hover{border-color:var(--linie-hell)}
.stelle.aktiv{border-color:var(--akzent)}
.kopfzeile{display:grid;grid-template-columns:42px 1fr auto;gap:12px;
  align-items:start}
.score{font-size:17px;font-weight:600;text-align:right;
  font-variant-numeric:tabular-nums;line-height:1.35}
.score.hoch{color:var(--gut)} .score.mittel{color:var(--mittel)}
.score.tief{color:var(--text-schwach)} .score.leer{color:var(--text-schwach);font-weight:400}
.titel{font-size:15px;font-weight:600;line-height:1.3;margin:0 0 3px}
.titel a{color:var(--text);text-decoration:none}
.titel a:hover{color:var(--akzent)}
.zeile2{display:flex;flex-wrap:wrap;gap:4px 11px;font-size:12px;
  color:var(--text-weich);align-items:center}
.rechts{text-align:right;font-size:11.5px;color:var(--text-schwach);
  white-space:nowrap;font-variant-numeric:tabular-nums}
.neu{display:inline-block;background:var(--akzent);color:#10141a;
  font-size:10px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  padding:1px 6px;border-radius:4px;margin-bottom:3px}
.frist{color:var(--stop);font-weight:600;display:block}
.frist.ruhig{color:var(--text-schwach);font-weight:400}

.pille{font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;
  padding:2px 7px;border-radius:5px;white-space:nowrap;font-weight:600}
.pille.remote{background:rgba(94,194,122,.16);color:var(--remote)}
.pille.hybrid{background:rgba(122,162,247,.16);color:var(--hybrid)}
.pille.onsite{background:rgba(224,112,95,.16);color:var(--onsite)}
.pille.unklar{background:rgba(107,118,134,.18);color:var(--text-weich)}
.zeit{font-variant-numeric:tabular-nums;font-weight:600;color:var(--text)}
.zeit.geschaetzt{font-weight:400;color:var(--text-weich)}
.aufgabe{font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;
  padding:2px 7px;border-radius:5px;background:var(--flaeche-hoch);
  color:var(--text-weich);border:1px solid var(--linie)}
.reibung{font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;
  padding:2px 7px;border-radius:5px;color:var(--stop);
  border:1px solid rgba(224,112,95,.35)}
.grundmarke{font-size:10px;text-transform:uppercase;letter-spacing:.05em;
  background:rgba(224,112,95,.16);color:var(--stop);padding:2px 6px;
  border-radius:4px;margin-right:6px;font-weight:700}
.stelle.gefiltert{opacity:.62}

details{margin-top:9px}
summary{font-size:11.5px;color:var(--text-schwach);cursor:pointer;
  list-style:none;display:inline-flex;align-items:center;gap:5px;
  padding:3px 0;user-select:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸";font-size:10px;transition:none}
details[open] summary::before{content:"▾"}
summary:hover{color:var(--text-weich)}
.detailfeld{margin-top:7px;padding-top:9px;border-top:1px solid var(--linie);
  font-size:12.5px;color:var(--text-weich)}
.detailfeld dl{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;
  margin:0 0 9px}
.detailfeld dt{color:var(--text-schwach);font-size:11.5px}
.detailfeld dd{margin:0}
.belege{margin:0;padding:0;list-style:none}
.belege li{padding-left:13px;position:relative;margin-bottom:5px;
  line-height:1.45;color:var(--text-weich)}
.belege li::before{content:"";position:absolute;left:0;top:9px;width:7px;
  height:1px;background:var(--linie-hell)}
.belege b{color:var(--text);font-weight:600}

.leer{padding:34px 0;color:var(--text-schwach)}
.fussnote{font-size:11.5px;color:var(--text-schwach);margin:6px 0 0}
footer{margin-top:44px;padding-top:16px;border-top:1px solid var(--linie);
  font-size:11.5px;color:var(--text-schwach);line-height:1.7}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

JS = """
(function(){
  var daten = JSON.parse(document.getElementById('daten').textContent);
  var filter = {archetyp:'alle', nurNeu:false, ohneEhrenamt:false,
                zeigeGefiltert:false, nurPassend:true};
  var sortierung = 'score';
  var farbmodus = 'modell';

  var FARBEN = {
    modell: {
      remote:['#5ec27a','vollständig remote — Entfernung egal'],
      hybrid:['#7aa2f7','teils vor Ort, teils mobil'],
      onsite:['#e0705f','Präsenz erwartet'],
      unklar:['#6b7686','kein Arbeitsmodell in der Anzeige genannt']
    },
    alter: {
      frisch:['#5ec27a','in den letzten 7 Tagen veröffentlicht'],
      mittel:['#7aa2f7','7 bis 21 Tage alt'],
      alt:['#e0b341','älter als 21 Tage'],
      unbekannt:['#6b7686','kein Datum in der Anzeige']
    },
    kategorie: {}
  };
  (daten.archetypen || []).forEach(function(a){
    FARBEN.kategorie[a.id] = [a.farbe, a.label];
  });

  function klasseAlter(d){
    if (!d) return 'unbekannt';
    var tage = (Date.now() - Date.parse(d)) / 86400000;
    if (tage <= 7) return 'frisch';
    if (tage <= 21) return 'mittel';
    return 'alt';
  }
  function schluessel(s){
    if (farbmodus === 'modell') return s.modell || 'unklar';
    if (farbmodus === 'alter') return klasseAlter(s.datum);
    return s.archetyp;
  }
  function farbe(s){
    var e = FARBEN[farbmodus][schluessel(s)];
    return e ? e[0] : '#6b7686';
  }

  function zahl(el, name){
    var v = el.dataset[name];
    return (v === '' || v === undefined) ? null : Number(v);
  }
  function bestwert(el){
    if (sortierung === 'fahrzeit'){
      var f = zahl(el,'fahrzeit'); return f === null ? 99999 : f;
    }
    if (sortierung === 'datum'){
      var d = el.dataset.datum || '';
      return d ? -Number(d.replace(/-/g,'')) : 99999;
    }
    var s = zahl(el,'score'); return s === null ? 99999 : -s;
  }

  function sichtbarkeit(el){
    if (filter.archetyp !== 'alle' && el.dataset.archetyp !== filter.archetyp) return false;
    if (filter.nurNeu && el.dataset.neu !== '1') return false;
    if (filter.ohneEhrenamt && el.dataset.ehrenamt === '1') return false;
    if (!filter.zeigeGefiltert && el.dataset.gefiltert !== '') return false;
    if (el.dataset.abgelaufen === '1' && !filter.zeigeGefiltert) return false;
    if (filter.nurPassend){
      var s = zahl(el,'score');
      if (s === null || s < 1) return false;
    }
    return true;
  }

  function anwenden(){
    var sichtbareIds = {};
    document.querySelectorAll('.stelle').forEach(function(el){
      var zeig = sichtbarkeit(el);
      el.hidden = !zeig;
      if (zeig) sichtbareIds[el.dataset.id] = true;
    });

    document.querySelectorAll('.gruppe').forEach(function(g){
      var liste = Array.prototype.slice.call(g.querySelectorAll('.stelle:not([hidden])'));
      liste.sort(function(a,b){ return bestwert(a) - bestwert(b); });
      liste.forEach(function(el){ g.appendChild(el); });
      g.hidden = liste.length === 0;
      var z = g.querySelector('.zaehler');
      if (z) z.textContent = liste.length;
      g.dataset.best = liste.length ? bestwert(liste[0]) : '';
    });

    // Kategorien bleiben, aber die mit dem besten Treffer steht oben.
    var behaelter = document.getElementById('gruppen');
    if (behaelter){
      var gruppen = Array.prototype.slice.call(behaelter.querySelectorAll('.gruppe'));
      gruppen.sort(function(a,b){
        var av=a.dataset.best, bv=b.dataset.best;
        if (av==='' && bv==='') return 0;
        if (av==='') return 1;
        if (bv==='') return -1;
        return Number(av)-Number(bv);
      });
      gruppen.forEach(function(g){ behaelter.appendChild(g); });
    }

    var alle = document.querySelectorAll('.stelle:not([hidden])').length;
    var leer = document.getElementById('leer');
    if (leer) leer.hidden = alle > 0;
    var zahlSichtbar = document.getElementById('zahlSichtbar');
    if (zahlSichtbar) zahlSichtbar.textContent = alle;

    zeichneKarte(sichtbareIds);
    zeichneLegende();
    zeichneBesten(sichtbareIds);
  }

  // Die staerksten Treffer quer ueber alle Kategorien. Bewusst keine zweiten
  // Karten, sondern Verweise: sonst stuende dieselbe Stelle zweimal im DOM und
  // Filter, Zaehler und Karte muessten sie doppelt behandeln.
  function zeichneBesten(sichtbareIds){
    var feld = document.getElementById('besten');
    if (!feld) return;
    var kandidaten = daten.stellen.filter(function(s){
      return sichtbareIds[s.id] && s.score != null;
    });
    kandidaten.sort(function(a,b){
      if (b.score !== a.score) return b.score - a.score;
      var am = a.minuten == null ? 99999 : a.minuten;
      var bm = b.minuten == null ? 99999 : b.minuten;
      return am - bm;
    });

    function fuelle(ziel, liste, leertext){
      var ul = document.getElementById(ziel);
      ul.innerHTML = '';
      if (!liste.length){
        var li = document.createElement('li');
        li.innerHTML = '<span class="leerzeile">' + leertext + '</span>';
        ul.appendChild(li);
        return;
      }
      liste.slice(0,6).forEach(function(s){
        var li = document.createElement('li');
        li.dataset.ziel = s.id;
        li.innerHTML =
          '<span class="bs" style="color:' + farbe(s) + '">'
          + (s.score > 0 ? '+' : '') + s.score + '</span>'
          + '<span class="bt" title="' + (s.arbeitgeber || '') + '">' + s.titel + '</span>'
          + '<span class="bm">' + (s.minuten == null ? '?' : s.minuten) + ' min'
          + (s.geschaetzt ? '~' : '') + '</span>';
        ul.appendChild(li);
      });
    }

    fuelle('bestenRemote',
           kandidaten.filter(function(s){ return s.modell === 'remote'; }),
           'Derzeit keine vollständig remote ausgeschriebene Stelle.');
    fuelle('bestenVorOrt',
           kandidaten.filter(function(s){ return s.modell !== 'remote'; }),
           'Keine Treffer bei den aktuellen Filtern.');
  }

  document.addEventListener('click', function(ev){
    var li = ev.target.closest && ev.target.closest('.bestenliste li[data-ziel]');
    if (!li) return;
    springeZu(li.dataset.ziel);
  });

  function springeZu(id){
    var zeile = document.querySelector('.stelle[data-id="' + CSS.escape(id) + '"]');
    if (!zeile) return;
    document.querySelectorAll('.stelle.aktiv').forEach(function(e){
      e.classList.remove('aktiv');
    });
    zeile.classList.add('aktiv');
    zeile.scrollIntoView({block:'center'});
  }

  // --- Karte: Radialdiagramm, kein Kartendienst --------------------------
  var SVG = 'http://www.w3.org/2000/svg';
  var RINGE = [30,45,60,75];
  function zeichneKarte(sichtbareIds){
    var svg = document.getElementById('karte');
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var B = 400, cx = B/2, cy = B/2, rmax = B/2 - 26;
    svg.setAttribute('viewBox', '0 0 ' + B + ' ' + B);

    RINGE.forEach(function(m){
      var r = m / RINGE[RINGE.length-1] * rmax;
      var k = document.createElementNS(SVG,'circle');
      k.setAttribute('cx',cx); k.setAttribute('cy',cy); k.setAttribute('r',r);
      k.setAttribute('class','ring'); svg.appendChild(k);
      var t = document.createElementNS(SVG,'text');
      t.setAttribute('x',cx+3); t.setAttribute('y',cy-r+11);
      t.setAttribute('class','ringtext'); t.textContent = m+' min';
      svg.appendChild(t);
    });

    var punkte = daten.stellen.filter(function(s){
      return sichtbareIds[s.id] && s.breite && s.laenge && s.minuten != null;
    });
    punkte.sort(function(a,b){ return b.minuten - a.minuten; });

    punkte.forEach(function(s){
      var dLat = s.breite - daten.anker.breite;
      var dLon = (s.laenge - daten.anker.laenge)
                 * Math.cos(daten.anker.breite * Math.PI/180);
      var winkel = Math.atan2(dLon, dLat);
      var r = Math.min(s.minuten, RINGE[RINGE.length-1]) / RINGE[RINGE.length-1] * rmax;
      var k = document.createElementNS(SVG,'circle');
      k.setAttribute('cx', cx + r*Math.sin(winkel));
      k.setAttribute('cy', cy - r*Math.cos(winkel));
      k.setAttribute('r', Math.max(4, Math.min(9, 4 + (s.score||0)*0.55)));
      k.setAttribute('fill', farbe(s));
      k.setAttribute('fill-opacity','.85');
      k.setAttribute('class','punkt');
      k.dataset.id = s.id;
      svg.appendChild(k);
    });

    var a = document.createElementNS(SVG,'circle');
    a.setAttribute('cx',cx); a.setAttribute('cy',cy); a.setAttribute('r',5);
    a.setAttribute('class','anker'); svg.appendChild(a);
    var at = document.createElementNS(SVG,'text');
    at.setAttribute('x',cx+9); at.setAttribute('y',cy+4);
    at.setAttribute('class','ankertext'); at.textContent = daten.anker.name;
    svg.appendChild(at);

    var ohne = daten.stellen.filter(function(s){
      return sichtbareIds[s.id] && !(s.breite && s.laenge);
    }).length;
    var hinweis = document.getElementById('ohneort');
    if (hinweis) hinweis.textContent = ohne
      ? ohne + ' sichtbare Anzeigen ohne Koordinaten — nur die Bundesagentur '
        + 'liefert welche. Sie stehen in der Liste, aber nicht auf der Karte.'
      : '';
  }

  function zeichneLegende(){
    var l = document.getElementById('legende');
    if (!l) return;
    l.innerHTML = '';
    Object.keys(FARBEN[farbmodus]).forEach(function(k){
      var e = FARBEN[farbmodus][k];
      var s = document.createElement('span');
      s.title = e[1];
      s.innerHTML = '<i class="punktprobe" style="background:'+e[0]+'"></i>'
                    + (farbmodus === 'kategorie' ? e[1] : k);
      l.appendChild(s);
    });
  }

  // --- Tooltip und Verknuepfung Karte <-> Liste --------------------------
  var tip = document.getElementById('tooltip');
  function zeige(s, x, y){
    var e = FARBEN[farbmodus][schluessel(s)];
    tip.innerHTML = '<b>' + s.titel + '</b>'
      + (s.arbeitgeber ? s.arbeitgeber + '<br>' : '')
      + (s.minuten != null ? s.minuten + ' min' + (s.geschaetzt ? ' (geschätzt)' : '') : '')
      + (s.ort ? ' · ' + s.ort : '')
      + '<br><em>Farbe: ' + (e ? e[1] : '—') + '</em>';
    tip.style.display = 'block';
    var b = tip.getBoundingClientRect();
    tip.style.left = Math.min(x + 14, window.innerWidth - b.width - 10) + 'px';
    tip.style.top  = Math.min(y + 14, window.innerHeight - b.height - 10) + 'px';
  }
  document.addEventListener('mouseover', function(ev){
    var k = ev.target.closest && ev.target.closest('#karte circle.punkt');
    if (!k) return;
    var s = daten.stellen.find(function(x){ return x.id === k.dataset.id; });
    if (s) zeige(s, ev.clientX, ev.clientY);
  });
  document.addEventListener('mouseout', function(ev){
    if (ev.target.closest && ev.target.closest('#karte circle.punkt'))
      tip.style.display = 'none';
  });
  document.addEventListener('click', function(ev){
    var k = ev.target.closest && ev.target.closest('#karte circle.punkt');
    if (!k) return;
    springeZu(k.dataset.id);
  });

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
  document.querySelectorAll('[data-farbe]').forEach(function(btn){
    btn.addEventListener('click', function(){
      farbmodus = btn.dataset.farbe;
      document.querySelectorAll('[data-farbe]').forEach(function(b){
        b.setAttribute('aria-pressed', String(b.dataset.farbe === farbmodus));
      });
      anwenden();
    });
  });

  anwenden();
})();
"""

ARCHETYP_FARBEN = ["#7aa2f7", "#5ec27a", "#e0b341", "#c98bdb", "#e0705f",
                   "#4fc4c4", "#c4a484"]


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


def standard_versteckt(stelle: dict[str, Any]) -> bool:
    """Wird diese Stelle im Auslieferungszustand ausgeblendet?

    Muss mit dem Startzustand von `filter` im JS uebereinstimmen. Wird an drei
    Stellen gebraucht — Zeilenrendering, Gruppenzaehler, Gruppensortierung —
    und steht deshalb hier zentral.
    """
    if stelle.get("gefiltert"):
        return True
    tage = _tage_bis(stelle.get("frist"))
    if tage is not None and tage < 0:
        return True
    passung = stelle.get("passung") or {}
    if passung.get("status") != "bewertet":
        return True
    return (passung.get("score") or 0) < 1


def _belege(stelle: dict[str, Any]) -> list[tuple[str, str]]:
    """Alle Urteile mit der Textstelle, aus der sie folgen."""
    screening = stelle.get("screening") or {}
    zeilen: list[tuple[str, str]] = []

    modell = stelle.get("arbeitsmodell") or {}
    if modell.get("beleg"):
        zeilen.append((f"Arbeitsmodell ({modell.get('modell')})", modell["beleg"]))
    erreichbar = stelle.get("erreichbar") or {}
    if erreichbar.get("hinweis"):
        zeilen.append(("Erreichbarkeit", erreichbar["hinweis"]))

    studium = screening.get("studium") or {}
    if studium.get("beleg"):
        kopf = ("Studium zwingend" if studium.get("stufe") == "hart"
                else "Studium mit Alternative")
        zeilen.append((kopf, studium["beleg"]))
    ehrenamt = screening.get("ehrenamtslogik") or {}
    if ehrenamt.get("beleg"):
        zeilen.append(("Ehrenamtslogik", ehrenamt["beleg"]))
    befristung = screening.get("befristung") or {}
    if befristung.get("beleg"):
        zeilen.append(("Befristung", befristung["beleg"]))
    for r in (stelle.get("passung") or {}).get("reibung") or []:
        zeilen.append((f"Reibung {r.get('gruppe')} ({r.get('gewicht')})",
                       str(r.get("beleg"))))
    return zeilen


MODELL_TITEL = {
    "remote": "Vollständig remote laut Anzeigentext",
    "hybrid": "Teils vor Ort, teils mobil",
    "onsite": "Präsenz erwartet",
    "unklar": "Kein Arbeitsmodell genannt — gegen die Unklar-Schwelle geprüft",
}


def _zeile(stelle: dict[str, Any]) -> str:
    screening = stelle.get("screening") or {}
    passung = stelle.get("passung") or {}
    score = passung.get("score")
    bewertet = passung.get("status") == "bewertet"

    if not bewertet:
        score_html = ('<div class="score leer" title="Keine Beschreibung — '
                      'kein Score, kein Urteil">–</div>')
    else:
        stufe = "hoch" if score >= 5 else ("mittel" if score >= 2 else "tief")
        score_html = (f'<div class="score {stufe}" title="Summe der getroffenen '
                      f'Aufgabengruppen minus Reibung">{score:+d}</div>')

    modell = (stelle.get("arbeitsmodell") or {}).get("modell", "unklar")
    fahrzeit = stelle.get("fahrzeit") or {}
    minuten = fahrzeit.get("minuten")
    geschaetzt = fahrzeit.get("geschaetzt")

    zeit_html = ""
    if minuten is not None:
        titel = ("geschätzt über " + str(fahrzeit.get("quelle"))
                 if geschaetzt else "OpenRouteService, PKW")
        zeit_html = (f'<span class="zeit{" geschaetzt" if geschaetzt else ""}" '
                     f'title="{esc(titel)}">{int(minuten)} min'
                     f'{"~" if geschaetzt else ""}</span>')
    else:
        zeit_html = '<span class="zeit geschaetzt" title="Keine Ortsangabe">? min</span>'

    zeile2 = [f'<span class="pille {esc(modell)}" '
              f'title="{esc(MODELL_TITEL.get(modell, ""))}">{esc(modell)}</span>',
              zeit_html]
    if stelle.get("arbeitgeber"):
        zeile2.append(esc(stelle["arbeitgeber"]))
    if stelle.get("ort"):
        zeile2.append(esc(stelle["ort"]))
    for a in passung.get("aufgaben") or []:
        zeile2.append(f'<span class="aufgabe">{esc(a)}</span>')
    for r in passung.get("reibung") or []:
        zeile2.append(f'<span class="reibung" title="{esc(r.get("beleg"))}">'
                      f'{esc(r.get("gruppe"))} {esc(r.get("gewicht"))}</span>')

    frist = stelle.get("frist")
    tage = _tage_bis(frist)
    abgelaufen = tage is not None and tage < 0
    frist_html = ""
    if frist:
        if abgelaufen:
            frist_html = f'<span class="frist">Frist abgelaufen</span>'
        elif tage is not None and tage <= 14:
            frist_html = f'<span class="frist">noch {tage} Tage</span>'
        else:
            frist_html = f'<span class="frist ruhig">Frist {esc(frist)}</span>'

    grund = stelle.get("gefiltert")
    grund_html = f'<span class="grundmarke">{esc(grund)}</span>' if grund else ""
    neu_html = '<span class="neu">neu</span>' if stelle.get("neu") else ""

    # --- Aufklappbarer Teil ------------------------------------------------
    fakten = []
    if stelle.get("entgelt"):
        fakten.append(("Vergütung", stelle["entgelt"]))
    if stelle.get("wochenstunden"):
        fakten.append(("Umfang", f"{stelle['wochenstunden']:g} h/Woche"))
    praesenz = (stelle.get("arbeitsmodell") or {}).get("praesenztage")
    if praesenz:
        fakten.append(("Präsenztage", f"{praesenz} pro Woche"))
    stufe_s = (screening.get("studium") or {}).get("stufe", "offen")
    fakten.append(("Studium", {"hart": "zwingend gefordert",
                               "weich": "oder vergleichbare Qualifikation",
                               "offen": "nicht gefordert"}[stufe_s]))
    fakten.append(("Befristung", "befristet"
                   if (screening.get("befristung") or {}).get("getroffen")
                   else "unbefristet oder ohne Angabe"))
    fakten.append(("Quelle", stelle.get("quelle", "")))
    auch = stelle.get("auch_gefunden_bei") or []
    if auch:
        fakten.append(("Auch gefunden bei",
                       ", ".join(sorted({a.get("quelle", "") for a in auch if a.get("quelle")}))))

    fakten_html = "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in fakten)
    belege = _belege(stelle)
    belege_html = ""
    if belege:
        eintraege = "".join(f"<li><b>{esc(k)}:</b> {esc(v)}</li>" for k, v in belege)
        belege_html = f'<ul class="belege">{eintraege}</ul>'

    versteckt = standard_versteckt(stelle)
    klassen = "stelle" + (" gefiltert" if grund else "")

    return f"""<article class="{klassen}"{' hidden' if versteckt else ''}
  data-id="{esc(stelle.get('id'))}" data-archetyp="{esc(stelle.get('archetyp'))}"
  data-neu="{'1' if stelle.get('neu') else '0'}"
  data-ehrenamt="{'1' if (screening.get('ehrenamtslogik') or {}).get('getroffen') else '0'}"
  data-abgelaufen="{'1' if abgelaufen else '0'}"
  data-gefiltert="{esc(grund or '')}"
  data-score="{score if bewertet else ''}"
  data-fahrzeit="{minuten if minuten is not None else ''}"
  data-datum="{esc(stelle.get('veroeffentlicht') or '')}">
  <div class="kopfzeile">
    {score_html}
    <div>
      <p class="titel">{grund_html}<a href="{esc(stelle.get('url'))}" target="_blank" rel="noopener">{esc(stelle.get('titel') or 'Ohne Titel')}</a></p>
      <div class="zeile2">{''.join(zeile2)}</div>
    </div>
    <div class="rechts">{neu_html}<br>{esc(stelle.get('veroeffentlicht') or '')}{frist_html}</div>
  </div>
  <details>
    <summary>Details</summary>
    <div class="detailfeld">
      <dl>{fakten_html}</dl>
      {belege_html}
    </div>
  </details>
</article>"""


def baue_dashboard(cfg: dict[str, Any], zustand: dict[str, Any], ziel: Path) -> Path:
    archetypen = sorted(cfg.get("archetypen", []), key=lambda a: a.get("rang", 99))
    for i, a in enumerate(archetypen):
        a["_farbe"] = ARCHETYP_FARBEN[i % len(ARCHETYP_FARBEN)]
    stellen = list(zustand.get("stellen", {}).values())

    stellen.sort(key=lambda s: s.get("veroeffentlicht") or "0000-00-00", reverse=True)
    stellen.sort(key=sortierschluessel)

    vorsortiert = []
    for a in archetypen:
        eintraege = [s for s in stellen if s.get("archetyp") == a["id"]]
        if not eintraege:
            continue
        sichtbare = [s for s in eintraege if not standard_versteckt(s)]
        scores = [x for x in ((s.get("passung") or {}).get("score")
                              for s in sichtbare) if x is not None]
        bestwert = -max(scores) if scores else 99999
        zeilen = "".join(_zeile(s) for s in eintraege)
        block = f"""<section class="gruppe" data-archetyp="{esc(a['id'])}">
  <h2><span style="color:{esc(a['_farbe'])}">■</span> {esc(a['label'])}
      <span class="zaehler">{len(sichtbare)}</span></h2>
  {zeilen}
</section>"""
        vorsortiert.append((bestwert, a.get("rang", 99), block))
    vorsortiert.sort(key=lambda x: (x[0], x[1]))
    gruppen_html = [b for _, _, b in vorsortiert]

    bekannte = {a["id"] for a in archetypen}
    reste = [s for s in stellen if s.get("archetyp") not in bekannte]
    if reste:
        sichtbar = sum(1 for s in reste if not standard_versteckt(s))
        gruppen_html.append(f"""<section class="gruppe" data-archetyp="_rest">
  <h2>Ohne aktuellen Archetyp <span class="zaehler">{sichtbar}</span></h2>
  {''.join(_zeile(s) for s in reste)}
</section>""")

    # Datenpaket fuer die Karte. Nur was gebraucht wird — nicht der Volltext.
    standort = cfg.get("standort") or {}
    karte = {
        "anker": {"breite": float(standort.get("breite", 50.7536)),
                  "laenge": float(standort.get("laenge", 7.7369)),
                  "name": standort.get("ort") or standort.get("wo") or ""},
        "archetypen": [{"id": a["id"], "label": a["label"], "farbe": a["_farbe"]}
                       for a in archetypen],
        "stellen": [{
            "id": s.get("id"), "titel": s.get("titel"),
            "arbeitgeber": s.get("arbeitgeber"), "ort": s.get("ort"),
            "breite": s.get("breite"), "laenge": s.get("laenge"),
            "minuten": (s.get("fahrzeit") or {}).get("minuten"),
            "geschaetzt": (s.get("fahrzeit") or {}).get("geschaetzt"),
            "modell": (s.get("arbeitsmodell") or {}).get("modell"),
            "score": (s.get("passung") or {}).get("score"),
            "archetyp": s.get("archetyp"),
            "datum": s.get("veroeffentlicht"),
        } for s in stellen],
    }

    laeufe = zustand.get("laeufe", [])
    letzter = laeufe[-1] if laeufe else {}
    stand = datetime.now(timezone.utc).strftime("%d.%m.%Y, %H:%M UTC")
    gefiltert = letzter.get("gefiltert") or {}
    gefiltert_text = ", ".join(f"{esc(g)} {esc(z)}" for g, z in gefiltert.items()) or "keine"

    archetyp_knoepfe = "".join(
        f'<button data-filter="archetyp" data-wert="{esc(a["id"])}" '
        f'aria-pressed="false">{esc(a["label"])}</button>' for a in archetypen)

    doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jobradar</title>
<!-- Keine Web-Fonts, kein CDN, keine Kartenkacheln: die Seite macht null
     Fremdaufrufe. Die Karte ist ein SVG aus den Koordinaten der Anzeigen. -->
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Jobradar</h1>
  <span class="stand">Stand {esc(stand)} · Ankerpunkt {esc((cfg.get('standort') or {}).get('ort') or '')}</span>
</header>

<div class="kennzahlen">
  <div class="kennzahl"><b id="zahlSichtbar">0</b><span>angezeigt</span></div>
  <div class="kennzahl"><b>{esc(letzter.get('neu', 0))}</b><span>neu</span></div>
  <div class="kennzahl"><b>{esc(letzter.get('gesamt', 0))}</b><span>im Bestand</span></div>
  <div class="kennzahl"><b>{esc(sum(gefiltert.values()) if gefiltert else 0)}</b><span>ausgefiltert</span></div>
</div>

<div class="leiste">
  <div class="satz"><span class="kopf">Sortierung</span>
    <button data-sort="score" aria-pressed="true">Score</button>
    <button data-sort="fahrzeit" aria-pressed="false">Fahrzeit</button>
    <button data-sort="datum" aria-pressed="false">Datum</button>
  </div>
  <div class="satz"><span class="kopf">Farbe</span>
    <button data-farbe="modell" aria-pressed="true">Arbeitsmodell</button>
    <button data-farbe="alter" aria-pressed="false">Alter</button>
    <button data-farbe="kategorie" aria-pressed="false">Kategorie</button>
  </div>
  <div class="satz"><span class="kopf">Filter</span>
    <button data-filter="archetyp" data-wert="alle" aria-pressed="true">Alle</button>
    {archetyp_knoepfe}
  </div>
  <div class="satz">
    <button data-filter="nurNeu" aria-pressed="false">Nur neue</button>
    <button data-filter="ohneEhrenamt" aria-pressed="false">Ohne Ehrenamtslogik</button>
    <button data-filter="nurPassend" aria-pressed="true">Nur mit Aufgabenbezug</button>
    <button data-filter="zeigeGefiltert" aria-pressed="false">Ausgefilterte zeigen</button>
  </div>
</div>

<div class="spalten">
  <div>
    <section class="besten" id="besten">
      <h2>Beste Treffer</h2>
      <p class="unterzeile">Quer über alle Kategorien, nach Score. Folgt den
      gesetzten Filtern und der Sortierung. Klick springt zur Anzeige.</p>
      <div class="bestenspalten">
        <div class="bestenspalte">
          <h3><i class="punktprobe" style="background:var(--remote)"></i>Remote</h3>
          <ul class="bestenliste" id="bestenRemote"></ul>
        </div>
        <div class="bestenspalte">
          <h3><i class="punktprobe" style="background:var(--hybrid)"></i>Vor Ort oder hybrid</h3>
          <ul class="bestenliste" id="bestenVorOrt"></ul>
        </div>
      </div>
    </section>
    <div id="gruppen">{''.join(gruppen_html)}</div>
    <p class="leer" id="leer" hidden>Keine Anzeigen passen zu den gewählten Filtern.</p>
  </div>
  <aside class="kartenfeld">
    <h2>Wo liegt was</h2>
    <p>{esc(KARTE_HINWEIS)}</p>
    <svg id="karte" viewBox="0 0 400 400" role="img"
         aria-label="Stellen nach Fahrzeit und Himmelsrichtung"></svg>
    <div class="legende" id="legende"></div>
    <p class="ohneort" id="ohneort"></p>
  </aside>
</div>

<footer>
Bewertet wird der <b>Anzeigentext</b>, nicht die Berufsbezeichnung — ein Titelfilter entfernt zwangsläufig Passendes. Der Score summiert getroffene Aufgabengruppen und zieht Reibungsmuster ab.<br>
Entfernt werden nur drei Dinge: zu lange Fahrzeit, Umfang unter {esc((cfg.get('harte_filter') or {}).get('mindest_wochenstunden', 20))} Wochenstunden, zwingend gefordertes Studium. Zuletzt ausgefiltert: {gefiltert_text}. Über „Ausgefilterte zeigen“ nachprüfbar.<br>
Fahrzeiten sind PKW-Zeiten ab {esc((cfg.get('standort') or {}).get('ort') or '')}. Ein <code>~</code> heißt geschätzt (ohne <code>ORS_API_KEY</code>); bei Bahnanbindung weicht der Tür-zu-Tür-Wert ab.<br>
{esc(letzter.get('zusammengefuehrt', 0))} Duplikate zusammengeführt. Quellen: Bundesagentur für Arbeit, service.bund.de, einzelne Karriereseiten nach robots.txt-Prüfung. Die Statusfelder sind Mustererkennung, keine Rechtsauskunft — die Belegstellen stehen unter „Details“.
</footer>
</div>
<div id="tooltip"></div>
<script type="application/json" id="daten">{json.dumps(karte, ensure_ascii=False)}</script>
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
