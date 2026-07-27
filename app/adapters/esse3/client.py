"""Adapter verso le API ufficiali v1/v2 (upstream reale).

Principi:
- le credenziali upstream restano LATO SERVER, legate alla sessione
  (fix PRB-03: mai più la password sul dispositivo);
- timeout esplicito su ogni chiamata, circuit breaker condiviso;
- i percorsi NON confermati dalla spec non vengono inventati: dove il
  path reale non è ancora noto (bus, mense, foto) va configurato via
  variabile d'ambiente, altrimenti la rotta risponde 503 con codice
  `upstream_path_not_configured`. Niente TODO silenziosi.

ATTENZIONE — percorsi da riconfermare con swagger.json (tools/fetch_swagger.sh):
queste costanti derivano dalla documentazione pubblica osservata il
26-27/07/2026 e vanno verificate prima dell'uso in produzione.
"""
from __future__ import annotations

import logging

import httpx

from ...core.circuit import CircuitBreaker
from ...core.errors import (InvalidCredentials, NotFound, UpstreamContract,
                            UpstreamNotConfigured, UpstreamTimeout,
                            UpstreamUnavailable)
from ...domain.models import Career
from . import mappers

logger = logging.getLogger("v3.esse3")

LOGIN_PATH = "/UniparthenopeApp/v1/login"
PIANO_ID_PATH = "/UniparthenopeApp/v1/students/pianoId/{stu_id}"
EXAMS_PATH = "/UniparthenopeApp/v1/students/exams/{stu_id}/{piano_id}"
CHECK_APPELLO_PATH = "/UniparthenopeApp/v1/students/checkAppello/{cds_id}/{ad_id}"
BOOK_PATH = "/UniparthenopeApp/v1/students/bookExam/{cds_id}/{ad_id}/{app_id}"
DELETE_PATH = "/UniparthenopeApp/v1/students/deleteExam/{cds_id}/{ad_id}/{app_id}/{stu_id}"
RESERVATIONS_PATH = "/UniparthenopeApp/v1/students/getReservations/{mat_id}"
STUDENT_PHOTO_PATH = "/UniparthenopeApp/v1/general/image/{ref}"
PROFESSOR_PHOTO_PATH = "/UniparthenopeApp/v1/general/image_prof/{ref}"
BUS_PATH = "/Bus/v1/bus/{sede}"
BUS_SCHEDULE_PATH = "/Bus/v1/orari/{sede}"
DINING_PATH = "/Eating/v1/getAllToday"
REGISTER_DEVICE_PATH = "/Notifications/v1/registerDevice"
UNREGISTER_DEVICE_PATH = "/Notifications/v1/unregisterDevice"


def _int_or_none(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _find_first(value, *keys):
    """Cerca un identificatore noto senza assumere la forma del login legacy."""
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for child in value.values():
            found = _find_first(child, *keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_first(child, *keys)
            if found not in (None, ""):
                return found
    return None


class Esse3Transport:
    """HTTP client + circuit breaker condivisi fra tutte le sessioni."""

    def __init__(self, base_url: str, timeout_s: float = 5.0, settings=None) -> None:
        self.settings = settings
        self.breaker = CircuitBreaker()
        self.client = httpx.Client(
            base_url=base_url, timeout=timeout_s, follow_redirects=True,
            headers={"User-Agent": "uniparthenope-v3-gateway/1.0"})

    def request(self, method: str, path: str, *, auth=None,
                passthrough_5xx: bool = False, **kwargs) -> httpx.Response:
        self.breaker.guard()
        try:
            response = self.client.request(method, path, auth=auth, **kwargs)
        except httpx.TimeoutException as exc:
            self.breaker.record_failure()
            raise UpstreamTimeout(f"Timeout verso {path}") from exc
        except httpx.HTTPError as exc:
            self.breaker.record_failure()
            raise UpstreamUnavailable(f"Errore di rete verso {path}") from exc
        if response.status_code >= 500:
            self.breaker.record_failure()
            # Le interfacce legacy devono conservare status e payload reali.
            # Il namespace v3 continua invece a normalizzare il guasto in 503.
            if passthrough_5xx:
                return response
            raise UpstreamUnavailable(
                f"L'upstream ha risposto {response.status_code} su {path}")
        self.breaker.record_success()
        return response

    @staticmethod
    def json_of(response: httpx.Response, path: str):
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamContract(f"Risposta non JSON da {path}") from exc


class Esse3Adapter:
    """Adapter legato a una sessione (credenziali in memoria di processo)."""

    name = "esse3"

    def __init__(self, transport: Esse3Transport, username: str | None,
                 password: str | None) -> None:
        self._t = transport
        self._username = username
        self._password = password
        self._piano_ids: dict[int, int] = {}
        self._career_context: dict[int, Career] = {}

    @property
    def _auth(self):
        if self._username is None:
            return None
        return (self._username, self._password)

    @property
    def upstream_auth(self):
        """Credenziali usate solo server-side dal gateway completo."""
        return self._auth

    def _cfg(self, attr: str, feature: str) -> str:
        value = getattr(self._t.settings, attr, "") if self._t.settings else ""
        if not value:
            raise UpstreamNotConfigured(
                f"Percorso upstream per '{feature}' non ancora configurato: "
                f"impostare la variabile d'ambiente corrispondente dopo averlo "
                f"verificato su swagger.json. La v3 non inventa percorsi.")
        return value

    # -- auth -------------------------------------------------------------
    def login(self):
        response = self._t.request("GET", LOGIN_PATH, auth=self._auth)
        if response.status_code in (401, 403):
            raise InvalidCredentials("Username o password non validi.")
        data = self._t.json_of(response, LOGIN_PATH)
        if not isinstance(data, dict):
            raise UpstreamContract("Login: atteso oggetto JSON.")
        # La risposta reale di Esse3 annida i dati anagrafici e le carriere
        # dentro "user", non alla radice (bug corretto il 27/07/2026 dopo
        # test con account reale: la radice ha solo
        # authToken/credentials/expPwd/internalAuthToken/profili/user).
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        profile = {
            "username": self._username,
            "firstName": user.get("firstName") or user.get("nome") or "",
            "lastName": user.get("lastName") or user.get("cognome") or "",
            "email": user.get("email") or data.get("email") or "",
            "personId": _find_first(data, "personId", "persId", "pers_id"),
            "idAb": _find_first(data, "idAb", "id_ab"),
        }
        careers: list[Career] = []
        for tratto in user.get("trattiCarriera", []) or []:
            det = tratto.get("dettaglioTratto") or tratto
            career_id = _int_or_none(det.get("aaIscrId") or det.get("iscrId")
                                     or det.get("careerId"))
            if career_id is None:
                continue
            careers.append(Career(
                career_id=career_id,
                mat_id=_int_or_none(det.get("matId")),
                stu_id=_int_or_none(det.get("stuId")),
                cds_id=_int_or_none(det.get("cdsId")),
                # cdsDes vive sul tratto esterno, non in dettaglioTratto
                # (stesso tipo di errore del bug principale, trovato con
                # lo stesso test su account reale).
                cds_des=str(tratto.get("cdsDes") or det.get("cdsDes") or ""),
                active=True,
            ))
        if not careers:
            raise UpstreamContract(
                "Login riuscito ma nessuna carriera riconosciuta nella risposta: "
                "verificare le chiavi di trattiCarriera/dettaglioTratto.")
        return profile, careers

    def set_career_context(self, careers) -> None:
        self._career_context = {c.career_id: c for c in careers}

    # -- carriera -----------------------------------------------------------
    def get_plan(self, career_id: int, career: Career | None = None):
        target = career or self._career_context.get(career_id)
        if target is None or target.stu_id is None:
            raise UpstreamContract("Carriera priva di stuId: impossibile leggere il libretto.")
        piano_id = self._piano_ids.get(career_id)
        if piano_id is None:
            resp = self._t.request("GET", PIANO_ID_PATH.format(stu_id=target.stu_id),
                                   auth=self._auth)
            payload = self._t.json_of(resp, PIANO_ID_PATH)
            piano_id = _int_or_none(payload.get("pianoId") if isinstance(payload, dict)
                                    else payload)
            if piano_id is None:
                raise UpstreamContract("pianoId non presente nella risposta upstream.")
            self._piano_ids[career_id] = piano_id
        resp = self._t.request("GET", EXAMS_PATH.format(stu_id=target.stu_id,
                                                        piano_id=piano_id),
                               auth=self._auth)
        return mappers.map_plan(self._t.json_of(resp, EXAMS_PATH), career_id=career_id)

    def get_exam_sessions(self, career: Career, ad_id=None):
        if ad_id is None:
            raise UpstreamNotConfigured(
                "L'upstream v1/v2 non espone un elenco appelli aggregato noto: "
                "specificare adId (?adId=...) oppure configurare il percorso "
                "aggregato quando confermato dalla spec.")
        resp = self._t.request("GET", CHECK_APPELLO_PATH.format(cds_id=career.cds_id,
                                                                ad_id=ad_id),
                               auth=self._auth)
        return mappers.map_exam_sessions(self._t.json_of(resp, CHECK_APPELLO_PATH))

    # -- prenotazioni ------------------------------------------------------------
    def book_exam(self, career: Career, app_id: int, ad_id: int, adsce_id: int):
        if adsce_id is None:  # difesa in profondità: non deve mai accadere
            raise UpstreamContract("adsceId nullo: rifiutato PRIMA della chiamata upstream.")
        path = BOOK_PATH.format(cds_id=career.cds_id, ad_id=ad_id, app_id=app_id)
        payload = {"adsceId": adsce_id, "notaStu": ""}
        resp = self._t.request("POST", path, auth=self._auth, json=payload)
        if resp.status_code in (400, 409):
            from ...core.errors import Conflict
            raise Conflict("L'upstream ha rifiutato la prenotazione (già presente?).")
        return self._t.json_of(resp, path)

    def get_reservations(self, career: Career):
        resp = self._t.request("GET", RESERVATIONS_PATH.format(mat_id=career.mat_id),
                               auth=self._auth)
        return mappers.map_reservations(self._t.json_of(resp, RESERVATIONS_PATH))

    def delete_reservation(self, career: Career, reservation_id: str) -> bool:
        reservations, _ = self.get_reservations(career)
        target = next((r for r in reservations
                       if r.reservation_id == str(reservation_id)), None)
        if target is None:
            return False
        path = DELETE_PATH.format(cds_id=career.cds_id, ad_id=target.ad_id,
                                  app_id=target.app_id, stu_id=career.stu_id)
        resp = self._t.request("DELETE", path, auth=self._auth)
        if resp.status_code == 404:
            return False
        return True

    # -- foto (PRB-13) --------------------------------------------------------------
    def get_photo(self, kind: str, ref) -> bytes:
        template = STUDENT_PHOTO_PATH if kind == "student" else PROFESSOR_PHOTO_PATH
        resp = self._t.request("GET", template.format(ref=ref), auth=self._auth)
        if resp.status_code == 404:
            raise NotFound("Foto non presente a sistema.")
        return resp.content

    # -- servizi (PRB-16) -------------------------------------------------------------
    def bus_routes(self, sede="1"):
        bus_path = BUS_PATH.format(sede=sede)
        schedule_path = BUS_SCHEDULE_PATH.format(sede=sede)
        buses = self._t.json_of(self._t.request("GET", bus_path), bus_path)
        schedules = self._t.json_of(self._t.request("GET", schedule_path), schedule_path)
        return [{"sede": sede, "bus": buses, "schedule": schedules}]

    def dining_menus(self, date=None):
        # La spec pubblica non prevede un parametro data: viene ignorato solo
        # nell'upstream e resta disponibile nella facciata normalizzata.
        resp = self._t.request("GET", DINING_PATH)
        return self._t.json_of(resp, DINING_PATH)

    # -- dispositivi (PRB-15) -----------------------------------------------------------
    def register_device(self, username: str, token: str, platform: str = "unknown") -> None:
        self._t.request("POST", REGISTER_DEVICE_PATH, auth=self._auth,
                        json={"token": token, "device_model": platform,
                              "os_version": "unknown"})

    def unregister_device(self, token: str) -> None:
        self._t.request("POST", UNREGISTER_DEVICE_PATH, auth=self._auth,
                        json={"token": token})
