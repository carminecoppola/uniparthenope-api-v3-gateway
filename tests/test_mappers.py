"""Test dei mapper: righe malformate contate, date normalizzate, allow-list stati."""
import unittest

from app.adapters.esse3 import mappers


class MapperTests(unittest.TestCase):
    def test_plan_wrapper_and_malformed_rows(self):
        raw = {"dettaglioTratto": [
            {"adsceId": 1, "adId": 10, "adDes": "OK"},
            {"adId": 11},                 # manca adsceId → scartata
            {"adsceId": "x", "adId": 12}, # adsceId non numerico → scartata
            "non-un-dict",                # → scartata
        ]}
        entries, skipped = mappers.map_plan(raw, career_id=7)
        self.assertEqual(len(entries), 1)
        self.assertEqual(skipped, 3)
        self.assertEqual(entries[0].adsce_id, 1)
        self.assertEqual(entries[0].career_id, 7)

    def test_plan_accepts_key_variants(self):
        entries, skipped = mappers.map_plan([{"adsce_id": 5, "ad_id": 50}])
        self.assertEqual(skipped, 0)
        self.assertEqual(entries[0].adsce_id, 5)

    def test_date_normalization(self):
        self.assertEqual(mappers.normalize_date("15/09/2026"), "2026-09-15")
        self.assertEqual(mappers.normalize_date("2026-09-15"), "2026-09-15")
        self.assertEqual(mappers.normalize_date("2026-09-15T09:00:00"), "2026-09-15")
        self.assertEqual(mappers.normalize_date(None), "")
        self.assertEqual(mappers.normalize_date("boh"), "")

    def test_bookable_allow_list_not_deny_list(self):
        """Fix del bug upstream bad_status=[\"C\"]: allow-list {P, I}."""
        sessions, _ = mappers.map_exam_sessions([
            {"appId": 1, "adId": 1, "stato": "P"},
            {"appId": 2, "adId": 1, "stato": "I"},
            {"appId": 3, "adId": 1, "stato": "C"},
            {"appId": 4, "adId": 1, "stato": "Z"},  # stato ignoto → NON prenotabile
            {"appId": 5, "adId": 1},                  # stato assente → NON prenotabile
        ])
        bookable = {s.app_id: s.bookable for s in sessions}
        self.assertEqual(bookable, {1: True, 2: True, 3: False, 4: False, 5: False})

    def test_exam_sessions_preserve_teacher_and_extra_fields(self):
        """I client legacy mostrano docente/iscritti/note/finestra iscrizione:
        campi già presenti nel payload grezzo esse3, il mapper non deve
        più scartarli (a differenza di prima)."""
        sessions, _ = mappers.map_exam_sessions([{
            "appId": 1, "adId": 1, "stato": "P",
            "presidenteCognome": "ROSSI", "presidenteNome": "MARIO",
            "numIscritti": 42, "note": "Portare libretto",
            "desApp": "Appello scritto", "dataInizioIscr": "01/09/2026",
            "dataFineIscr": "10/09/2026",
        }])
        s = sessions[0]
        self.assertEqual(s.teacher, "Rossi")
        self.assertEqual(s.teacher_full, "Rossi Mario")
        self.assertEqual(s.enrolled_count, 42)
        self.assertEqual(s.note, "Portare libretto")
        self.assertEqual(s.description, "Appello scritto")
        self.assertEqual(s.registration_start, "2026-09-01")
        self.assertEqual(s.registration_end, "2026-09-10")

    def test_exam_sessions_extra_fields_default_empty_when_missing(self):
        """Riga minima (com'era prima): niente eccezioni, solo default vuoti."""
        sessions, skipped = mappers.map_exam_sessions([{"appId": 1, "adId": 1}])
        self.assertEqual(skipped, 0)
        s = sessions[0]
        self.assertEqual(s.teacher, "")
        self.assertEqual(s.teacher_full, "")
        self.assertIsNone(s.enrolled_count)

    def test_reservations_require_all_ids(self):
        rows = [
            {"reservationId": "r1", "appId": 1, "adId": 2, "adsceId": 3},
            {"reservationId": "r2", "appId": 1, "adId": 2},  # manca adsceId
        ]
        out, skipped = mappers.map_reservations(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(skipped, 1)


if __name__ == "__main__":
    unittest.main()
