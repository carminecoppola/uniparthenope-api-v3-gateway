"""Adapter ESSE3 simulato: nessuna rete, nessun dato reale.

Serve a: sviluppare offline, collaudare la logica v3 — inclusa la
cancellazione, senza toccare prenotazioni vere (PRB-14) — e far girare
i test automatici. I dati riproducono le FORME osservate nelle risposte
v1/v2, con le varianti di chiavi reali (adsceId vive nel libretto, NON
nell'appello: è esattamente il punto di PRB-12).
"""
from __future__ import annotations

import base64
import itertools

from ...core.errors import Conflict, Forbidden, InvalidCredentials, NotFound
from ...domain.models import Career
from . import mappers

# PNG 1×1 valido: placeholder foto senza alcun dato personale.
_PHOTO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

_RAW_PLAN = {
    "dettaglioTratto": [
        {"adsceId": 91001, "adId": 101, "adDes": "CALCOLO PARALLELO", "aaOffId": 2025},
        {"adsceId": 91002, "adId": 102, "adDes": "BASI DI DATI", "aaOffId": 2025},
        # Riga volutamente malformata (adsceId assente): il mapper deve
        # scartarla e contarla — mai lasciarla diventare un None upstream.
        {"adId": 103, "adDes": "RIGA CORROTTA"},
    ]
}

_RAW_SESSIONS = [
    {"appId": 501, "adId": 101, "adDes": "CALCOLO PARALLELO", "aaOffId": 2025,
     "stato": "P", "dataInizioApp": "15/09/2026"},
    {"appId": 502, "adId": 102, "adDes": "BASI DI DATI", "aaOffId": 2025,
     "stato": "C", "dataInizioApp": "18/09/2026"},
    # Appello di un insegnamento NON nel piano: deve produrre 422, non None.
    {"appId": 503, "adId": 999, "adDes": "INSEGNAMENTO FUORI PIANO", "aaOffId": 2025,
     "stato": "P", "dataInizioApp": "22/09/2026"},
]


class MockEsse3Adapter:
    name = "mock"

    def __init__(self) -> None:
        self._reservations: dict[str, dict] = {}
        self._devices: dict[str, dict] = {}
        self._ids = itertools.count(70001)

    # -- auth ------------------------------------------------------------
    def login(self, username: str, password: str):
        if not username or password != "demo":
            raise InvalidCredentials("In modalità mock la password è 'demo'.")
        career = Career(career_id=2001, mat_id=124680, stu_id=33445,
                        cds_id=310, cds_des="INFORMATICA", active=True)
        profile = {"username": username, "firstName": "Studente",
                   "lastName": "Di Prova",
                   "email": f"{username}@studenti.uniparthenope.it"}
        return profile, [career]

    # -- carriera ----------------------------------------------------------
    def get_plan(self, career_id: int):
        return mappers.map_plan(_RAW_PLAN, career_id=career_id)

    def get_exam_sessions(self, career, ad_id=None):
        sessions, skipped = mappers.map_exam_sessions(_RAW_SESSIONS)
        if ad_id is not None:
            sessions = [s for s in sessions if s.ad_id == ad_id]
        return sessions, skipped

    def get_exam_sessions_batch(self, career, ad_ids: list[int], workers: int | None = None):
        """Stessa forma del ritorno dell'adapter reale (sessioni, scartate,
        errori_per_ad), cosi' la route non deve ramificare tra mock e reale."""
        sessions, skipped = mappers.map_exam_sessions(_RAW_SESSIONS)
        ad_ids_set = set(ad_ids)
        filtrate = [s for s in sessions if s.ad_id in ad_ids_set]
        errori = {ad_id: {"status": 403, "message": "adId inesistente nei dati mock"}
                 for ad_id in ad_ids if ad_id not in {s.ad_id for s in sessions}}
        return filtrate, skipped, errori

    # -- prenotazioni ---------------------------------------------------------
    def book_exam(self, career, app_id: int, ad_id: int, adsce_id: int):
        assert adsce_id is not None, "il servizio non deve mai arrivare qui con None"
        for existing in self._reservations.values():
            if existing["appId"] == app_id and existing["careerId"] == career.career_id:
                raise Conflict("Prenotazione già presente per questo appello.")
        rid = str(next(self._ids))
        record = {"reservationId": rid, "appId": app_id, "adId": ad_id,
                  "adsceId": adsce_id, "careerId": career.career_id}
        self._reservations[rid] = record
        return record

    def get_reservations(self, career):
        raw = [r for r in self._reservations.values()
               if r["careerId"] == career.career_id]
        return mappers.map_reservations(raw)

    def delete_reservation(self, career, reservation_id: str) -> bool:
        record = self._reservations.get(str(reservation_id))
        if record is None:
            return False  # idempotente: già assente
        if record["careerId"] != career.career_id:
            raise Forbidden("La prenotazione appartiene a un'altra carriera.")
        del self._reservations[str(reservation_id)]
        return True

    # -- foto (PRB-13) -----------------------------------------------------------
    def get_photo(self, kind: str, ref) -> bytes:
        if str(ref) == "nophoto":
            # "Foto non caricata" è uno stato di dominio previsto, non un guasto.
            raise NotFound("Foto non presente a sistema.")
        return _PHOTO_PNG

    # -- servizi (PRB-16) ----------------------------------------------------------
    def bus_routes(self, sede="1"):
        return [
            {"id": "R1", "name": "Centro Direzionale ↔ Monte di Dio",
             "stops": ["Centro Direzionale", "Municipio", "Via Acton", "Monte di Dio"],
             "frequencyMinutes": 20, "firstRun": "07:30", "lastRun": "19:30"},
            {"id": "R2", "name": "Napoli Centrale ↔ Villa Doria",
             "stops": ["Garibaldi", "Università", "Villa Doria"],
             "frequencyMinutes": 30, "firstRun": "08:00", "lastRun": "18:00"},
        ]

    def dining_menus(self, date: str | None = None):
        return [{
            "site": "Mensa Centro Direzionale",
            "date": date or "2026-07-27",
            "lunch": {"first": ["Pasta al pomodoro", "Riso alle verdure"],
                      "second": ["Pollo al forno", "Frittata"],
                      "side": ["Insalata", "Patate al forno"]},
        }]

    # -- dispositivi (PRB-15) ---------------------------------------------------------
    def register_device(self, username: str, token: str, platform: str = "unknown") -> None:
        self._devices[token] = {"username": username, "platform": platform}

    def unregister_device(self, token: str) -> None:
        self._devices.pop(token, None)
