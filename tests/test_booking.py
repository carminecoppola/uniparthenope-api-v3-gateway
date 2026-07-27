"""Test del fix PRB-12 (adsceId) e PRB-14 (cancellazione idempotente).

Girano offline, senza framework e senza rete: python3 -m unittest.
"""
import unittest

from app.adapters.esse3.mock import MockEsse3Adapter
from app.core.errors import Conflict, Forbidden, PlanEntryNotFound
from app.domain.booking import BookingService
from app.domain.models import Career


class RecordingAdapter(MockEsse3Adapter):
    """Registra le chiamate a book_exam per verificare che, in caso di 422,
    NESSUNA chiamata raggiunga l'upstream."""

    def __init__(self):
        super().__init__()
        self.book_calls = []

    def book_exam(self, career, app_id, ad_id, adsce_id):
        self.book_calls.append({"appId": app_id, "adId": ad_id, "adsceId": adsce_id})
        return super().book_exam(career, app_id=app_id, ad_id=ad_id, adsce_id=adsce_id)


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.adapter = RecordingAdapter()
        self.service = BookingService(self.adapter)
        self.career = Career(career_id=2001, mat_id=124680, stu_id=33445, cds_id=310)

    # -- risoluzione adsceId (PRB-12) ----------------------------------
    def test_resolve_adsce_id_from_plan(self):
        self.assertEqual(self.service.resolve_adsce_id(2001, 101), 91001)
        self.assertEqual(self.service.resolve_adsce_id(2001, 102, aa_off_id=2025), 91002)

    def test_resolve_missing_activity_raises_422(self):
        with self.assertRaises(PlanEntryNotFound) as ctx:
            self.service.resolve_adsce_id(2001, 999)
        self.assertEqual(ctx.exception.status, 422)
        self.assertEqual(ctx.exception.code, "plan_entry_not_found")

    def test_no_upstream_call_when_not_in_plan(self):
        """Il difetto originale: adsceId None inoltrato comunque. Qui: MAI."""
        with self.assertRaises(PlanEntryNotFound):
            self.service.book(self.career, app_id=503, ad_id=999)
        self.assertEqual(self.adapter.book_calls, [])

    # -- prenotazione -----------------------------------------------------
    def test_book_sends_resolved_adsce_id_never_none(self):
        result = self.service.book(self.career, app_id=501, ad_id=101)
        self.assertFalse(result["dryRun"])
        self.assertEqual(len(self.adapter.book_calls), 1)
        self.assertEqual(self.adapter.book_calls[0]["adsceId"], 91001)
        self.assertIsNotNone(self.adapter.book_calls[0]["adsceId"])

    def test_book_dry_run_does_not_mutate(self):
        result = self.service.book(self.career, app_id=501, ad_id=101, dry_run=True)
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["wouldBook"]["adsceId"], 91001)
        self.assertEqual(self.adapter.book_calls, [])
        reservations, _ = self.adapter.get_reservations(self.career)
        self.assertEqual(reservations, [])

    def test_double_booking_conflict(self):
        self.service.book(self.career, app_id=501, ad_id=101)
        with self.assertRaises(Conflict):
            self.service.book(self.career, app_id=501, ad_id=101)

    # -- cancellazione (PRB-14) ------------------------------------------------
    def test_cancel_is_idempotent(self):
        booked = self.service.book(self.career, app_id=501, ad_id=101)
        rid = booked["reservation"]["reservationId"]
        first = self.service.cancel(self.career, rid)
        self.assertTrue(first["deleted"])
        self.assertFalse(first["alreadyGone"])
        second = self.service.cancel(self.career, rid)  # niente eccezione
        self.assertFalse(second["deleted"])
        self.assertTrue(second["alreadyGone"])

    def test_cancel_dry_run_reports_without_deleting(self):
        booked = self.service.book(self.career, app_id=501, ad_id=101)
        rid = booked["reservation"]["reservationId"]
        preview = self.service.cancel(self.career, rid, dry_run=True)
        self.assertTrue(preview["wouldDelete"])
        reservations, _ = self.adapter.get_reservations(self.career)
        self.assertEqual(len(reservations), 1)  # ancora presente

    def test_cancel_other_career_forbidden(self):
        booked = self.service.book(self.career, app_id=501, ad_id=101)
        rid = booked["reservation"]["reservationId"]
        other = Career(career_id=9999)
        with self.assertRaises(Forbidden):
            self.service.cancel(other, rid)

    # -- appelli --------------------------------------------------------------
    def test_exam_sessions_bookable_resolved_server_side(self):
        sessions = self.service.exam_sessions(self.career)
        by_app = {s.app_id: s for s in sessions}
        self.assertTrue(by_app[501].bookable)          # stato P
        self.assertFalse(by_app[502].bookable)         # stato C
        self.assertIn("non prenotabile", by_app[502].reason)

    # -- foto (PRB-13) ------------------------------------------------------------
    def test_photo_returns_valid_png(self):
        data = self.adapter.get_photo("student", "qualcuno")
        self.assertTrue(data.startswith(b"\x89PNG"))

    def test_photo_missing_is_404_domain_state(self):
        from app.core.errors import NotFound
        with self.assertRaises(NotFound):
            self.adapter.get_photo("professor", "nophoto")


if __name__ == "__main__":
    unittest.main()
