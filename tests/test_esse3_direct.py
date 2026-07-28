"""Test del client diretto esse3.cineca.it per gli appelli (paginazione,
fallback page/rows, dedupe, batch multi-AD).

Nessuna rete reale: httpx.MockTransport intercetta le richieste.
"""
import unittest

try:
    import httpx
    from app.adapters.esse3.client import Esse3DirectTransport
    from app.core.errors import UpstreamContract
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    httpx = None
    _IMPORT_ERROR = exc


def _make_transport(handler) -> "Esse3DirectTransport":
    t = Esse3DirectTransport("https://esse3.example/e3rest/api", 5.0, settings=None)
    t.client = httpx.Client(base_url="https://esse3.example/e3rest/api",
                            transport=httpx.MockTransport(handler))
    return t


@unittest.skipIf(httpx is None, f"httpx non disponibile: {_IMPORT_ERROR}")
class PaginationTests(unittest.TestCase):
    def test_single_page_short_stops_immediately(self):
        """Una pagina più corta della page_size: niente seconda richiesta."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(dict(request.url.params))
            return httpx.Response(200, json=[{"appId": 1}, {"appId": 2}])

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=200, max_pages=25)

        self.assertEqual(status, 200)
        self.assertEqual(len(righe), 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["start"], "0")
        self.assertEqual(calls[0]["limit"], "200")

    def test_multi_page_follows_start_offset(self):
        """Due pagine piene (page_size=2) + una corta: si ferma alla terza."""
        pages = [
            [{"appId": 1}, {"appId": 2}],
            [{"appId": 3}, {"appId": 4}],
            [{"appId": 5}],
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params["start"])
            idx = start // 2
            return httpx.Response(200, json=pages[idx] if idx < len(pages) else [])

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=2, max_pages=25)

        self.assertEqual(status, 200)
        self.assertEqual([r["appId"] for r in righe], [1, 2, 3, 4, 5])

    def test_server_ignores_pagination_dedupe_stops_loop(self):
        """Se esse3 ignorasse start/limit e ripetesse sempre la stessa
        pagina, la deduplica deve fermare la raccolta invece di girare
        fino a max_pages (o peggio, all'infinito)."""
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(200, json=[{"appId": 1}, {"appId": 2}])

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=2, max_pages=25)

        self.assertEqual(status, 200)
        self.assertEqual(len(righe), 2)  # non duplicati
        self.assertEqual(call_count["n"], 2)  # 1a pagina + 1 ripetuta rilevata, poi stop

    def test_max_pages_is_a_hard_cap(self):
        """Un server che risponde sempre pagine piene DIVERSE non deve
        far girare la raccolta oltre max_pages."""
        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params["start"])
            # Ogni pagina ha appId diversi, mai vuota, mai più corta.
            return httpx.Response(200, json=[{"appId": start}, {"appId": start + 1}])

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=2, max_pages=3)

        self.assertEqual(status, 200)
        self.assertEqual(len(righe), 6)  # 3 pagine * 2 righe, non di più

    def test_first_page_error_returns_status_and_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"retErrMsg": "AD fuori carriera"})

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=200, max_pages=25)

        self.assertEqual(status, 403)
        self.assertEqual(righe, [])
        self.assertEqual(errore["retErrMsg"], "AD fuori carriera")

    def test_later_page_error_keeps_partial_results(self):
        """Se la PRIMA pagina va bene ma una successiva fallisce, si tiene
        quanto raccolto invece di buttare via un risultato parziale valido.
        Status 403 (non innesca il fallback page/rows, a differenza di
        400/500): qui si testa solo la logica "tieni il parziale"."""
        def handler(request: httpx.Request) -> httpx.Response:
            start = int(request.url.params["start"])
            if start == 0:
                return httpx.Response(200, json=[{"appId": 1}, {"appId": 2}])
            return httpx.Response(403, json={"retErrMsg": "boom"})

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=2, max_pages=25)

        self.assertEqual(status, 200)
        self.assertEqual(len(righe), 2)


@unittest.skipIf(httpx is None, f"httpx non disponibile: {_IMPORT_ERROR}")
class FallbackPaginationTests(unittest.TestCase):
    """Copre la richiesta esplicita del prof: se esse3 rifiuta start/limit
    con 400/500, va tentato page/rows prima di arrendersi. Non ancora
    verificato con credenziali reali — qui si verifica solo che il
    meccanismo di fallback funzioni come progettato."""

    def test_start_limit_rejected_falls_back_to_page_rows(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            params = dict(request.url.params)
            seen.append(params)
            if "start" in params:
                return httpx.Response(400, json={"retErrMsg": "start/limit non supportato"})
            self.assertEqual(params["page"], "1")
            self.assertEqual(params["rows"], "200")
            return httpx.Response(200, json=[{"appId": 1}])

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=200, max_pages=25)

        self.assertEqual(status, 200)
        self.assertEqual(len(righe), 1)
        self.assertEqual(len(seen), 2)  # tentativo start/limit + fallback page/rows

    def test_both_pagination_styles_rejected_returns_original_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"retErrMsg": "parametro non valido"})

        t = _make_transport(handler)
        righe, status, errore = t.fetch_all_pages(
            cds_id=1, ad_id=1, auth=("u", "p"), page_size=200, max_pages=25)

        self.assertEqual(status, 400)
        self.assertEqual(errore["retErrMsg"], "parametro non valido")

    def test_success_on_first_try_never_calls_fallback(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=[])

        t = _make_transport(handler)
        t.fetch_all_pages(cds_id=1, ad_id=1, auth=("u", "p"),
                          page_size=200, max_pages=25)
        self.assertEqual(calls["n"], 1)


@unittest.skipIf(httpx is None, f"httpx non disponibile: {_IMPORT_ERROR}")
class BatchTests(unittest.TestCase):
    def test_batch_one_failing_ad_does_not_break_others(self):
        def handler(request: httpx.Request) -> httpx.Response:
            ad_id = request.url.path.rsplit("/", 1)[-1]
            if ad_id == "666":
                return httpx.Response(403, json={"retErrMsg": "fuori carriera"})
            return httpx.Response(200, json=[{"appId": int(ad_id) * 10}])

        t = _make_transport(handler)
        risultato = t.fetch_batch(cds_id=1, ad_ids=[101, 666, 102], auth=("u", "p"),
                                  workers=3, page_size=200, max_pages=25)

        self.assertEqual(risultato[101]["status"], 200)
        self.assertEqual(risultato[101]["items"], [{"appId": 1010}])
        self.assertEqual(risultato[666]["status"], 403)
        self.assertEqual(risultato[666]["errMsg"], "fuori carriera")
        self.assertEqual(risultato[102]["status"], 200)

    def test_batch_covers_every_requested_ad_exactly_once(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        t = _make_transport(handler)
        ad_ids = [1, 2, 3, 4, 5]
        risultato = t.fetch_batch(cds_id=1, ad_ids=ad_ids, auth=("u", "p"),
                                  workers=2, page_size=200, max_pages=25)
        self.assertEqual(sorted(risultato.keys()), ad_ids)


if __name__ == "__main__":
    unittest.main()
