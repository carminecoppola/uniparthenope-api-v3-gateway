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
from concurrent.futures import ThreadPoolExecutor

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
CHECK_EXAM_PATH = "/UniparthenopeApp/v1/students/checkExams/{mat_id}/{adsce_id}"
STUDENT_PHOTO_PATH = "/UniparthenopeApp/v1/general/image/{ref}"
PROFESSOR_PHOTO_PATH = "/UniparthenopeApp/v1/general/image_prof/{ref}"
CALESA_APPELLI_PATH = "/calesa-service-v1/appelli/{cds_id}/{ad_id}"
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


class Esse3DirectTransport:
    """Client HTTP diretto verso esse3.cineca.it, SOLO per gli appelli.

    Perché non passa dal backend legacy: quello espone solo la prima
    pagina di `calesa-service-v1/appelli` (nessun parametro start/limit),
    quindi per un insegnamento con molti appelli storici i client vedono
    solo i più vecchi. Qui si pagina fino in fondo.

    Credenziali: le STESSE Basic Auth (username:password) dell'utente —
    confermato che esse3.cineca.it le accetta direttamente, il backend
    legacy fa esattamente lo stesso passaggio (vedi login_v1.py di
    riferimento). Circuit breaker separato da quello del backend legacy:
    un guasto qui non deve far scattare 503 sulle chiamate v1/v2.
    """

    def __init__(self, base_url: str, timeout_s: float, settings=None) -> None:
        self.settings = settings
        self.breaker = CircuitBreaker()
        self.client = httpx.Client(
            base_url=base_url, timeout=timeout_s, follow_redirects=True,
            headers={"User-Agent": "uniparthenope-v3-gateway/1.0"})

    def _get(self, path: str, *, auth, params: dict) -> httpx.Response:
        self.breaker.guard()
        try:
            return self.client.get(path, auth=auth, params=params)
        except httpx.TimeoutException as exc:
            self.breaker.record_failure()
            raise UpstreamTimeout(f"Timeout verso esse3 {path}") from exc
        except httpx.HTTPError as exc:
            self.breaker.record_failure()
            raise UpstreamUnavailable(f"Errore di rete verso esse3 {path}") from exc

    def fetch_page(self, cds_id, ad_id, start: int, page_size: int,
                   auth) -> httpx.Response:
        """Una pagina di appelli.

        Prova prima `start`/`limit`. Se esse3 la rifiuta (400/412/500) prova
        `page`/`rows` (convenzione paginazione alternativa, usata da altre
        viste e3rest note). Verificato il 28/07/2026 con credenziali reali:
        la causa più comune di rifiuto NON è il nome dei parametri ma un
        `limit` troppo alto (esse3 accetta solo ≤100, da cui il default di
        APPELLI_PAGE_SIZE) — 412 incluso qui per coprire lo stesso caso se
        capitasse con un page_size diverso da quello di default. Se anche
        il fallback fallisce, si ritorna la risposta ORIGINALE (start/limit),
        più diretta da diagnosticare di un doppio errore.
        """
        path = CALESA_APPELLI_PATH.format(cds_id=cds_id, ad_id=ad_id)
        response = self._get(path, auth=auth,
                             params={"start": start, "limit": page_size})

        if response.status_code in (400, 412, 500):
            page_number = start // page_size + 1
            fallback = self._get(path, auth=auth,
                                 params={"page": page_number, "rows": page_size})
            if fallback.status_code < 400:
                logger.info(
                    "APPELLI paginazione start/limit rifiutata (status=%s): "
                    "uso page/rows, funziona (cdsId=%s adId=%s)",
                    response.status_code, cds_id, ad_id)
                response = fallback

        if response.status_code >= 500:
            self.breaker.record_failure()
        else:
            self.breaker.record_success()
        return response

    def fetch_all_pages(self, cds_id, ad_id, auth, page_size: int,
                        max_pages: int) -> tuple[list[dict], int, dict | None]:
        """Scorre tutte le pagine di un AD. Ritorna (righe, status, errore).

        status=200 con righe eventualmente vuote se l'AD non ha appelli;
        status diverso da 200 solo se la PRIMA pagina fallisce (se una
        pagina successiva fallisce si tiene quanto raccolto finora, non si
        butta via un risultato parziale valido).
        """
        raccolti: list[dict] = []
        visti: set = set()
        start = 0

        for _ in range(max_pages):
            response = self.fetch_page(cds_id, ad_id, start, page_size, auth)

            if response.status_code != 200:
                if raccolti:
                    break
                try:
                    errore = response.json()
                except ValueError:
                    errore = {"retErrMsg": response.text[:200]}
                return [], response.status_code, errore

            try:
                pagina = response.json()
            except ValueError as exc:
                raise UpstreamContract(
                    f"Risposta non JSON da esse3 (cdsId={cds_id} adId={ad_id})") from exc

            if not isinstance(pagina, list) or len(pagina) == 0:
                break

            nuovi = 0
            for item in pagina:
                if not isinstance(item, dict):
                    continue
                chiave = item.get("appId")
                # Se esse3 ignorasse start/limit la seconda pagina sarebbe
                # identica alla prima: la deduplica evita un loop infinito
                # silenzioso invece di fidarsi ciecamente della paginazione.
                if chiave is not None and chiave in visti:
                    continue
                visti.add(chiave)
                raccolti.append(item)
                nuovi += 1

            if nuovi == 0 or len(pagina) < page_size:
                break
            start += page_size

        return raccolti, 200, None

    def fetch_batch(self, cds_id, ad_ids: list, auth, workers: int,
                    page_size: int, max_pages: int) -> dict:
        """Più AD in parallelo. Ritorna {adId: {status, items, errMsg}}.

        Un AD in errore (es. 403 fuori piano) non deve buttare giù gli
        altri: l'errore resta confinato alla sua chiave nel risultato.
        """
        def scarica(ad_id):
            try:
                righe, status, errore = self.fetch_all_pages(
                    cds_id, ad_id, auth, page_size, max_pages)
                if status != 200:
                    return ad_id, {"status": status,
                                   "errMsg": (errore or {}).get("retErrMsg", ""),
                                   "items": []}
                return ad_id, {"status": 200, "errMsg": "", "items": righe}
            except Exception as exc:  # AD singolo: mai far cadere l'intero batch
                logger.warning("APPELLI batch: adId=%s fallito: %s", ad_id, exc)
                return ad_id, {"status": 500, "errMsg": str(exc), "items": []}

        risultato: dict = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for ad_id, esito in pool.map(scarica, ad_ids):
                risultato[ad_id] = esito
        return risultato


class Esse3Adapter:
    """Adapter legato a una sessione (credenziali in memoria di processo)."""

    name = "esse3"

    def __init__(self, transport: Esse3Transport, username: str | None,
                 password: str | None,
                 direct_transport: "Esse3DirectTransport | None" = None) -> None:
        self._t = transport
        self._direct = direct_transport
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
            "docenteId": _int_or_none(user.get("docenteId")),
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
        if not careers and profile["docenteId"] is None:
            # Un docente puro non ha trattiCarriera (e' un dato da studente):
            # solo se manca ANCHE il docenteId non sappiamo interpretare la
            # risposta, altrimenti e' un login legittimo senza carriera.
            raise UpstreamContract(
                "Login riuscito ma nessuna carriera ne' docenteId nella "
                "risposta: verificare le chiavi di trattiCarriera/docenteId.")
        return profile, careers

    def _open_web_client(self, settings):
        """Login SSO (Shibboleth) su un client httpx dedicato: la stessa
        area web di ESSE3 serve sia il Calendario Esami sia le altre
        pagine docente (es. Laureandi assegnati). Non accetta più Basic
        Auth diretta (verificato il 30/07/2026: /auth/Logon.do reindirizza
        sempre all'IdP Shibboleth dell'ateneo).
        """
        if self._auth is None:
            raise InvalidCredentials(
                "Nessuna credenziale disponibile per il login web ESSE3.")
        if not getattr(settings, "esse3_web_base", ""):
            raise UpstreamNotConfigured(
                "ESSE3_WEB_BASE non configurato: impostare la variabile "
                "d'ambiente per abilitare le funzioni web del docente.")
        from .web_calendar import perform_shibboleth_login
        client = httpx.Client(
            base_url=settings.esse3_web_base.rstrip("/"),
            timeout=settings.esse3_web_timeout_s, follow_redirects=True,
            headers={"User-Agent": "uniparthenope-v3-gateway/3.1"})
        try:
            perform_shibboleth_login(client, settings.esse3_web_base,
                                     self._username, self._password)
        except httpx.TimeoutException as exc:
            client.close()
            raise UpstreamTimeout("Timeout verso il login SSO di ESSE3.") from exc
        except httpx.HTTPError as exc:
            client.close()
            raise UpstreamUnavailable("Errore di rete verso il login SSO di ESSE3.") from exc
        except Exception:
            client.close()
            raise
        return client

    def open_web_calendar(self, settings):
        """Adapter del Calendario Esami per la sessione corrente (appelli
        docente). Nome del metodo comune a mock e reale: la rotta non deve
        ramificare fra le due modalità, come già per `do_login`.
        """
        from .web_calendar import WebCalendarAdapter
        client = self._open_web_client(settings)
        return WebCalendarAdapter(client, settings.esse3_web_dry_run_writes)

    def open_graduation(self, settings):
        """Adapter delle tesi assegnate (Laureandi assegnati). Stesso nome
        di metodo comune a mock e reale."""
        from .graduation import GraduationAdapter
        client = self._open_web_client(settings)
        return GraduationAdapter(client)

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
                "Specificare adId (?adId=...) oppure adIds (?adIds=1,2,3) "
                "per più insegnamenti in una sola chiamata.")
        if self._direct is None:
            # Nessun client diretto configurato (es. wiring di test): resta
            # il passthrough legacy, solo prima pagina.
            resp = self._t.request("GET", CHECK_APPELLO_PATH.format(
                cds_id=career.cds_id, ad_id=ad_id), auth=self._auth)
            return mappers.map_exam_sessions(self._t.json_of(resp, CHECK_APPELLO_PATH))

        settings = self._t.settings
        page_size = getattr(settings, "appelli_page_size", 200) if settings else 200
        max_pages = getattr(settings, "appelli_max_pages", 25) if settings else 25
        righe, status, errore = self._direct.fetch_all_pages(
            career.cds_id, ad_id, self._auth, page_size, max_pages)
        if status != 200:
            raise UpstreamContract(
                f"esse3 ha risposto {status} per adId={ad_id}: "
                f"{(errore or {}).get('retErrMsg', '')}")
        return mappers.map_exam_sessions(righe)

    def get_exam_sessions_batch(self, career: Career, ad_ids: list[int],
                                workers: int | None = None):
        """Appelli di più insegnamenti in parallelo (chiamata diretta a esse3,
        paginata). Ritorna (sessioni_mappate, scartate, errori_per_ad).

        Un adId che fallisce non fa fallire gli altri: finisce in
        `errori_per_ad` (adId -> {status, message}) e viene semplicemente
        escluso dai risultati, non solleva. Il CODICE numerico è incluso
        esplicitamente (non solo il messaggio testuale di esse3, che spesso
        non contiene il numero): un 403 "Security failed" su un adId che
        risulta comunque nel libretto è quasi sempre "nessun appello aperto
        ora", non un vero errore — il chiamante deve poterlo distinguere
        senza fare parsing di stringhe.
        """
        if self._direct is None:
            raise UpstreamNotConfigured(
                "Client diretto esse3 non configurato per questa sessione.")
        settings = self._t.settings
        page_size = getattr(settings, "appelli_page_size", 100) if settings else 100
        max_pages = getattr(settings, "appelli_max_pages", 25) if settings else 25
        default_workers = getattr(settings, "appelli_workers", 5) if settings else 5
        max_workers = getattr(settings, "appelli_max_workers", 20) if settings else 20

        n = max(1, min(workers or default_workers, max_workers, len(ad_ids)))
        grezzo = self._direct.fetch_batch(career.cds_id, ad_ids, self._auth,
                                          n, page_size, max_pages)

        sessioni = []
        scartate_tot = 0
        errori: dict[int, dict] = {}
        for ad_id, esito in grezzo.items():
            if esito["status"] != 200:
                errori[ad_id] = {"status": esito["status"],
                                 "message": esito["errMsg"] or ""}
                continue
            mappate, scartate = mappers.map_exam_sessions(esito["items"])
            sessioni.extend(mappate)
            scartate_tot += scartate
        return sessioni, scartate_tot, errori

    # -- esiti del libretto --------------------------------------------------------
    def get_exam_outcomes_batch(self, career: Career, adsce_ids: list[int],
                                workers: int | None = None):
        """Legge in parallelo l'esito (stato/voto) di più righe di libretto.

        Prima di questa API il client chiamava checkExams un adsceId alla
        volta (schermata Corsi lenta con carriere piene). Ritorna
        (esiti_mappati, errori_per_adsceId): un insegnamento che fallisce
        non fa fallire gli altri, resta nel dizionario errori con lo status
        HTTP originale, esattamente come già fa get_exam_sessions_batch per
        gli appelli.
        """
        if career.mat_id is None:
            raise UpstreamContract(
                "Carriera priva di matId: impossibile leggere gli esiti.")
        if not adsce_ids:
            return {}, {}

        settings = self._t.settings
        default_workers = getattr(settings, "plan_outcome_workers", 8) if settings else 8
        max_workers = getattr(settings, "plan_outcome_max_workers", 20) if settings else 20
        timeout = getattr(settings, "plan_outcome_timeout_s", 6.0) if settings else 6.0
        n = max(1, min(workers or default_workers, max_workers, len(adsce_ids)))

        def leggi(adsce_id):
            path = CHECK_EXAM_PATH.format(mat_id=career.mat_id, adsce_id=adsce_id)
            try:
                resp = self._t.request("GET", path, auth=self._auth, timeout=timeout)
                return adsce_id, mappers.map_exam_outcome(self._t.json_of(resp, path)), None
            except Exception as exc:  # una riga non deve far cadere il batch
                status = getattr(exc, "status", 502)
                logger.warning("Esito libretto: adsceId=%s fallito: %s", adsce_id, exc)
                return adsce_id, None, {"status": status, "message": str(exc)}

        outcomes: dict[int, dict] = {}
        errors: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=n) as pool:
            for adsce_id, outcome, error in pool.map(leggi, adsce_ids):
                if error is not None:
                    errors[adsce_id] = error
                elif outcome is not None:
                    outcomes[adsce_id] = outcome
        return outcomes, errors

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
