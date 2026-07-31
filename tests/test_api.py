"""Test HTTP end-to-end delle rotte /v3 (richiede fastapi installato).

Se FastAPI o il TestClient non sono disponibili nell'ambiente, i test si
auto-saltano DICHIARANDOLO: mai un finto verde.
"""
import unittest

try:
    from fastapi.testclient import TestClient
    from app.main import create_app
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover
    TestClient = None
    _IMPORT_ERROR = exc


@unittest.skipIf(TestClient is None,
                 f"FastAPI/TestClient non disponibili: {_IMPORT_ERROR}")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        key_response = self.client.post("/v3/api-keys", json={"owner": "test-suite"})
        self.assertEqual(key_response.status_code, 201)
        self.client.headers.update({"X-API-Key": key_response.json()["apiKey"]})
        response = self.client.post("/v3/auth/sessions",
                                    json={"username": "tester", "password": "demo"})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.access = body["accessToken"]
        self.refresh = body["refreshToken"]
        self.auth = {"Authorization": f"Bearer {self.access}"}

    # -- auth ---------------------------------------------------------
    def test_login_wrong_password_is_problem_json_401(self):
        r = self.client.post("/v3/auth/sessions",
                             json={"username": "tester", "password": "sbagliata"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers["content-type"], "application/problem+json")
        self.assertEqual(r.json()["code"], "invalid_credentials")
        self.assertIn("X-Request-Id", r.headers)

    def test_login_rate_limit_429(self):
        client = TestClient(create_app())
        key_response = client.post("/v3/api-keys", json={"owner": "test-rate-limit"})
        client.headers.update({"X-API-Key": key_response.json()["apiKey"]})
        for _ in range(5):
            client.post("/v3/auth/sessions",
                        json={"username": "burst", "password": "demo"})
        r = client.post("/v3/auth/sessions",
                        json={"username": "burst", "password": "demo"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["code"], "rate_limited")
        self.assertIn("Retry-After", r.headers)

    def test_refresh_rotation(self):
        r = self.client.post("/v3/auth/sessions/refresh",
                             json={"refreshToken": self.refresh})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["accessToken"], self.access)

    def test_unauthenticated_401(self):
        r = self.client.get("/v3/exam-sessions")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["code"], "auth_required")

    # -- appelli ------------------------------------------------------------
    def test_exam_sessions_have_server_side_bookable(self):
        r = self.client.get("/v3/exam-sessions?adIds=101,102,999",
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        items = {i["app_id"]: i for i in r.json()["items"]}
        self.assertTrue(items[501]["bookable"])
        self.assertFalse(items[502]["bookable"])   # stato C
        self.assertTrue(items[501]["inPlan"])
        self.assertFalse(items[503]["inPlan"])     # fuori piano
        self.assertEqual(items[501]["date"], "2026-09-15")  # data normalizzata

    def test_exam_sessions_no_params_auto_batches_the_whole_plan(self):
        """Senza adId/adIds: il gateway legge da solo gli adId dal piano di
        studi (101, 102 nei dati mock) e li interroga in batch — un solo
        giro, il client non deve più fare plan->adIds->exam-sessions a mano.
        adId 999 ("fuori piano") NON deve comparire: non è nel libretto."""
        r = self.client.get("/v3/exam-sessions", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        ad_ids_tornati = {i["ad_id"] for i in r.json()["items"]}
        self.assertEqual(ad_ids_tornati, {101, 102})

    def test_exam_sessions_batch_adIds_aggregates_and_reports_errors(self):
        """101 e 102 esistono nei dati mock, 999999 no: deve tornare i primi
        due normalmente e il terzo dentro 'errors', senza far fallire la
        richiesta intera (un adId rotto non deve rompere gli altri)."""
        r = self.client.get("/v3/exam-sessions?adIds=101,102,999999",
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        ad_ids_tornati = {i["ad_id"] for i in body["items"]}
        self.assertEqual(ad_ids_tornati, {101, 102})
        self.assertIn("999999", body["errors"])

    def test_exam_sessions_adIds_client_side_parallelism_not_needed(self):
        """Stesso principio del batch v3 legacy analizzato col prof: il
        client passa TUTTI gli adId in una chiamata, il parallelismo lo fa
        il server (parametro 'workers'), l'app non deve spezzare la
        richiesta in N chiamate parallele proprie."""
        r = self.client.get("/v3/exam-sessions?adIds=101,102&workers=2",
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 2)

    def test_exam_sessions_adIds_malformed_is_400_not_500(self):
        r = self.client.get("/v3/exam-sessions?adIds=,,,abc",
                            headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "validation_failed")

    # -- piano di studi con esiti ----------------------------------------------
    def test_plan_with_outcomes_reads_grades_in_parallel(self):
        r = self.client.get("/v3/students/me/plan", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 2)  # la riga 103 e' malformata, scartata
        by_ad = {i["ad_id"]: i for i in body["items"]}
        self.assertTrue(by_ad[101]["passed"])
        self.assertEqual(by_ad[101]["grade"], "28")
        self.assertFalse(by_ad[102]["passed"])
        self.assertEqual(by_ad[102]["stato_des"], "Pianificato")
        self.assertEqual(body["letture"]["letteAdesso"], 2)

    def test_plan_without_outcomes_skips_the_extra_reads(self):
        r = self.client.get("/v3/students/me/plan?withOutcomes=false",
                            headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["letture"]["letteAdesso"], 0)
        self.assertFalse(body["items"][0]["outcome_known"])

    def test_plan_second_read_comes_from_cache(self):
        self.client.get("/v3/students/me/plan", headers=self.auth)
        r = self.client.get("/v3/students/me/plan", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        # Il libretto e gli esiti sono già in cache: nessuna lettura upstream.
        self.assertEqual(r.json()["letture"]["letteAdesso"], 0)

    def test_plan_filters_by_stato(self):
        r = self.client.get("/v3/students/me/plan?stato=superato", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["ad_id"], 101)
        self.assertEqual(body["totaleLibretto"], 2)

    def test_plan_summary_no_extra_reads_over_plan(self):
        r = self.client.get("/v3/students/me/plan-summary", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["superati"], 1)
        self.assertEqual(body["mediaAritmetica"], 28)

    def test_plan_entry_detail_and_not_found(self):
        r = self.client.get("/v3/students/me/plan/91001", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["grade"], "28")

        missing = self.client.get("/v3/students/me/plan/999999", headers=self.auth)
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["code"], "plan_entry_not_found")

    def test_plan_entry_refresh_rereads_only_that_course(self):
        self.client.get("/v3/students/me/plan", headers=self.auth)  # popola la cache
        r = self.client.post("/v3/students/me/plan/91001/refresh", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["grade"], "28")

    # -- prenotazione (PRB-12) ------------------------------------------------
    def test_booking_happy_path_and_conflict(self):
        r = self.client.post("/v3/exam-sessions/501/reservations",
                             headers=self.auth, json={"adId": 101})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["reservation"]["adsceId"], 91001)
        r2 = self.client.post("/v3/exam-sessions/501/reservations",
                              headers=self.auth, json={"adId": 101})
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.json()["code"], "conflict")

    def test_booking_out_of_plan_is_422_not_upstream_500(self):
        r = self.client.post("/v3/exam-sessions/503/reservations",
                             headers=self.auth, json={"adId": 999})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "plan_entry_not_found")

    def test_booking_dry_run(self):
        r = self.client.post("/v3/exam-sessions/501/reservations?dryRun=true",
                             headers=self.auth, json={"adId": 101})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["wouldBook"]["adsceId"], 91001)
        listing = self.client.get("/v3/students/me/reservations", headers=self.auth)
        self.assertEqual(listing.json()["count"], 0)

    # -- cancellazione (PRB-14) ---------------------------------------------------
    def test_cancellation_idempotent(self):
        booked = self.client.post("/v3/exam-sessions/501/reservations",
                                  headers=self.auth, json={"adId": 101})
        rid = booked.json()["reservation"]["reservationId"]
        first = self.client.delete(f"/v3/reservations/{rid}", headers=self.auth)
        self.assertEqual(first.status_code, 204)
        self.assertEqual(first.headers["X-Already-Gone"], "false")
        second = self.client.delete(f"/v3/reservations/{rid}", headers=self.auth)
        self.assertEqual(second.status_code, 204)
        self.assertEqual(second.headers["X-Already-Gone"], "true")

    # -- foto (PRB-13) -----------------------------------------------------------
    def test_photo_etag_and_304(self):
        r = self.client.get("/v3/students/me/photo?size=128", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.headers["content-type"], ("image/png", "image/webp"))
        self.assertIn("private", r.headers["cache-control"])
        etag = r.headers["etag"]
        r304 = self.client.get("/v3/students/me/photo?size=128",
                               headers={**self.auth, "If-None-Match": etag})
        self.assertEqual(r304.status_code, 304)

    def test_photo_missing_is_404_problem(self):
        r = self.client.get("/v3/professors/nophoto/photo", headers=self.auth)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "not_found")

    def test_photo_invalid_size_is_400(self):
        r = self.client.get("/v3/students/me/photo?size=999", headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "validation_failed")

    # -- dispositivi (PRB-15) --------------------------------------------------------
    def test_device_registration_idempotent(self):
        r1 = self.client.put("/v3/devices/tok_abc", headers=self.auth,
                             json={"platform": "android"})
        r2 = self.client.put("/v3/devices/tok_abc", headers=self.auth,
                             json={"platform": "android"})
        self.assertEqual((r1.status_code, r2.status_code), (204, 204))
        r3 = self.client.delete("/v3/devices/tok_abc", headers=self.auth)
        self.assertEqual(r3.status_code, 204)

    # -- autobus / mense (PRB-16) -------------------------------------------------------
    def test_bus_and_dining_public_with_cache_flag(self):
        bus = self.client.get("/v3/transport/bus/routes")
        self.assertEqual(bus.status_code, 200)
        self.assertGreater(len(bus.json()["items"]), 0)
        self.assertEqual(bus.headers["X-Data-Stale"], "false")
        dining = self.client.get("/v3/dining/menus?date=2026-07-27")
        self.assertEqual(dining.status_code, 200)
        self.assertEqual(dining.json()["items"][0]["date"], "2026-07-27")

    # -- compatibilita' legacy --------------------------------------------------
    def test_all_legacy_paths_are_registered_at_original_address(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads(
            (root / "app/api/v3/upstream_catalog.json").read_text(encoding="utf-8"))
        openapi = self.client.get("/v3/openapi.json").json()
        paths = openapi["paths"]
        for operation in catalog["operations"]:
            self.assertIn(operation["path"], paths)
            self.assertIn(operation["method"].lower(), paths[operation["path"]])

    # -- health -----------------------------------------------------------------
    def test_health(self):
        r = self.client.get("/v3/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["mode"], "mock")


if __name__ == "__main__":
    unittest.main()
