"""Testet den Karriereseiten-Watcher gegen simuliertes HTML, ohne Netz."""
import sys
import urllib.robotparser
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from jobradar.seiten import RobotsWaechter, SeitenQuelle  # noqa: E402

HTML = """
<html><body>
<nav><a href="/impressum">Impressum</a><a href="/datenschutz">Datenschutz</a></nav>
<main id="inhalt">
  <h1>Stellen</h1>
  <a href="/stellen/mitarbeiter-oeffentlichkeitsarbeit.pdf">Mitarbeiter*in Öffentlichkeitsarbeit (m/w/d)</a>
  <a href="/ausschreibung/gebietsbetreuung-2026">Ausschreibung Gebietsbetreuung 2026</a>
  <a href="/stellen/foej">FÖJ-Platz bei uns</a>
  <a href="/aktuelles/apfelernte">Apfelernte 2026</a>
  <a href="/kurz">kurz</a>
</main>
</body></html>
"""


class FakeAntwort:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_linkextraktion():
    session = mock.Mock(spec=requests.Session)
    session.get.return_value = FakeAntwort(HTML)

    quelle = SeitenQuelle(session, pause=0)
    # robots.txt-Pruefung fuer diesen Test kurzschliessen
    quelle.robots.erlaubt = lambda url: (True, "Test")

    treffer = quelle.hole({
        "label": "Testquelle",
        "arbeitgeber": "Beispiel e.V.",
        "ort": "Eitorf",
        "archetyp": "naturschutz",
        "url": "https://beispiel.de/stellen/",
        "link_muster": "stelle|ausschreibung",
        "link_ausschluss": "datenschutz|impressum|foej",
    })

    titel = [t["titel"] for t in treffer]
    print("Linkextraktion:")
    for t in titel:
        print(f"  · {t}")

    assert "Mitarbeiter*in Öffentlichkeitsarbeit (m/w/d)" in titel
    assert "Ausschreibung Gebietsbetreuung 2026" in titel
    assert not any("FÖJ" in t for t in titel), "Ausschlussmuster hat nicht gegriffen"
    assert not any("Apfelernte" in t for t in titel), "Nicht-Stelle durchgerutscht"
    assert not any("kurz" == t for t in titel), "Zu kurzer Linktext durchgerutscht"
    assert all(t["url"].startswith("https://beispiel.de/") for t in treffer), \
        "Relative Links nicht aufgeloest"
    print(f"  [ok ] {len(treffer)} Treffer, Rauschen gefiltert")


def test_robots_untersagt():
    session = mock.Mock(spec=requests.Session)
    session.get.return_value = FakeAntwort("User-agent: *\nDisallow: /stellen\n")

    waechter = RobotsWaechter(session)
    erlaubt, grund = waechter.erlaubt("https://gesperrt.de/stellen/liste")
    print(f"robots.txt gesperrt:\n  [{'ok ' if not erlaubt else 'FEHLER'}] {grund}")
    assert not erlaubt

    erlaubt2, _ = waechter.erlaubt("https://gesperrt.de/ueber-uns")
    print(f"  [{'ok ' if erlaubt2 else 'FEHLER'}] andere Pfade bleiben erlaubt")
    assert erlaubt2


def test_robots_ueberspringt_quelle():
    """Eine gesperrte Quelle darf nichts liefern und muss protokolliert werden."""
    session = mock.Mock(spec=requests.Session)
    session.get.return_value = FakeAntwort(HTML)

    quelle = SeitenQuelle(session, pause=0)
    quelle.robots.erlaubt = lambda url: (False, "robots.txt untersagt")

    treffer = quelle.hole({
        "label": "Gesperrte Quelle",
        "url": "https://gesperrt.de/stellen",
        "link_muster": "stelle",
    })
    print("Gesperrte Quelle:")
    print(f"  [{'ok ' if treffer == [] else 'FEHLER'}] keine Treffer geliefert")
    assert treffer == []
    assert quelle.uebersprungen and "Gesperrte Quelle" in quelle.uebersprungen[0]
    print(f"  [ok ] protokolliert: {quelle.uebersprungen[0]}")


DETAILSEITE = """
<html><body>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Mitarbeiter*in Öffentlichkeitsarbeit (m/w/d)",
  "datePosted": "2026-07-27",
  "validThrough": "2026-08-21T23:59",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {"@type": "Organization", "name": "NABU Rheinland-Pfalz"},
  "jobLocation": {"@type": "Place", "address": {
      "@type": "PostalAddress", "addressLocality": "Holler", "postalCode": "56412"}},
  "description": "<p>Fundierte Kenntnisse in Naturschutz, Artenschutz und \\u00d6kologie. Eine abgeschlossene Berufsausbildung bzw. ein abgeschlossenes Studium oder eine vergleichbare Ausbildung im Bereich Kommunikation. Erfahrungen in der Verbandsarbeit oder Zusammenarbeit mit Ehrenamtlichen.</p>"
}
</script>
</body></html>
"""

# Variante: @graph-Container statt flachem Objekt
GRAPH_SEITE = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebSite","name":"Beispielseite"},
  {"@type":["JobPosting"],"title":"Videoredakteur*in",
   "hiringOrganization":"Kreis Siegen-Wittgenstein",
   "datePosted":"2026-08-01","validThrough":"2026-09-15",
   "jobLocation":{"address":{"addressLocality":"Siegen"}},
   "description":"Videoproduktion und Schnitt."}
]}
</script>
</body></html>
"""


def test_jsonld():
    from bs4 import BeautifulSoup

    from jobradar.seiten import lies_jobposting

    print("JSON-LD, flaches Objekt:")
    jobs = lies_jobposting(BeautifulSoup(DETAILSEITE, "html.parser"))
    assert len(jobs) == 1, f"erwartet 1 Treffer, bekommen {len(jobs)}"
    j = jobs[0]
    print(f"  · {j['titel']}")
    print(f"    {j['arbeitgeber']} | {j['ort']} | veroeff {j['veroeffentlicht']} | Frist {j['frist']}")
    assert j["arbeitgeber"] == "NABU Rheinland-Pfalz"
    assert j["ort"] == "Holler 56412"
    assert j["veroeffentlicht"] == "2026-07-27"
    assert j["frist"] == "2026-08-21", "validThrough nicht auf Datum gekuerzt"
    assert "Ehrenamtlichen" in j["volltext"], "HTML im description nicht entfernt"
    assert "<p>" not in j["volltext"]
    print("  [ok ] alle Felder korrekt")

    print("JSON-LD, @graph-Container:")
    jobs2 = lies_jobposting(BeautifulSoup(GRAPH_SEITE, "html.parser"))
    assert len(jobs2) == 1, "JobPosting im @graph nicht gefunden"
    assert jobs2[0]["arbeitgeber"] == "Kreis Siegen-Wittgenstein", \
        "hiringOrganization als String nicht verarbeitet"
    assert jobs2[0]["ort"] == "Siegen"
    print(f"  [ok ] {jobs2[0]['titel']} — {jobs2[0]['arbeitgeber']}")

    print("JSON-LD, kein Markup:")
    leer = lies_jobposting(BeautifulSoup("<html><body><p>nichts</p></body></html>",
                                         "html.parser"))
    assert leer == []
    print("  [ok ] leere Liste statt Absturz")


def test_details_folgen():
    """Detailseite wird nachgeladen und ueberschreibt die geratenen Felder."""
    session = mock.Mock(spec=requests.Session)
    session.get.side_effect = [FakeAntwort(HTML), FakeAntwort(DETAILSEITE),
                               FakeAntwort(DETAILSEITE)]

    quelle = SeitenQuelle(session, pause=0)
    quelle.robots.erlaubt = lambda url: (True, "Test")

    treffer = quelle.hole({
        "label": "Testquelle",
        "arbeitgeber": "Platzhalter e.V.",
        "url": "https://beispiel.de/stellen/",
        "link_muster": "stelle|ausschreibung",
        "link_ausschluss": "datenschutz|impressum|foej",
        "details_folgen": True,
        "max_details": 2,
    })

    print("Detailseiten folgen:")
    erster = treffer[0]
    print(f"  · {erster['titel']}")
    print(f"    Arbeitgeber {erster['arbeitgeber']} | Frist {erster['frist']}")
    assert erster["arbeitgeber"] == "NABU Rheinland-Pfalz", \
        "Platzhalter wurde nicht ueberschrieben"
    assert erster["frist"] == "2026-08-21"
    assert erster["_strukturiert"] is True
    assert len(erster["_volltext"]) > 100, "Volltext nicht uebernommen"
    print("  [ok ] Felder aus Markup uebernommen, Volltext vorhanden")


def test_screening_auf_volltext():
    """Der aus JSON-LD gewonnene Volltext muss das Screening tatsaechlich fuettern."""
    import yaml

    from jobradar.scan import Screener

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    from bs4 import BeautifulSoup

    from jobradar.seiten import lies_jobposting

    job = lies_jobposting(BeautifulSoup(DETAILSEITE, "html.parser"))[0]
    r = Screener(cfg["screening"]).run(job["volltext"])

    print("Screening auf JSON-LD-Volltext:")
    print(f"  studium={r['studium']['stufe']} ehrenamt={r['ehrenamtslogik']['getroffen']}")
    assert r["studium"]["stufe"] == "weich", "Studium-Alternative nicht erkannt"
    assert r["ehrenamtslogik"]["getroffen"], "Ehrenamtslogik nicht erkannt"
    print("  [ok ] beide Kriterien greifen — Titel allein haette nichts gefunden")


if __name__ == "__main__":
    test_linkextraktion()
    test_robots_untersagt()
    test_robots_ueberspringt_quelle()
    test_jsonld()
    test_details_folgen()
    test_screening_auf_volltext()
    print("\nAlles durchgelaufen.")
