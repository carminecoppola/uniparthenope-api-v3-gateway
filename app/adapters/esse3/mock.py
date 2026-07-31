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

from ...core.errors import (Conflict, Forbidden, InvalidCredentials, NotFound,
                            ValidationFailed)
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


class MockWebCalendarAdapter:
    """Simula il Calendario Esami docente (appelli) senza rete.

    Stessa interfaccia di `WebCalendarAdapter` (list/new_form/edit_form/save),
    cosi' l'app puo' essere sviluppata e provata end-to-end in modalità mock
    PRIMA di un test con credenziali docente reali, senza toccare mai ESSE3.
    """

    def __init__(self) -> None:
        from .web_calendar import EDITABLE, READ_ONLY, REQUIRED
        self._editable, self._read_only, self._required = EDITABLE, READ_ONLY, REQUIRED
        self._items: dict[int, dict] = {
            9001: {"cdsId": 10256, "adId": 2649, "aaId": 2025, "tipoProva": "PF",
                   "dataAppello": "2026-09-10", "ora": "09", "minuti": "30",
                   "iscrizioniDal": "2026-08-01", "iscrizioniAl": "2026-09-09",
                   "descrizione": "Appello di Settembre (prova)", "note": "",
                   "edificioId": "", "aulaId": "", "postiMax": "", "tipoEsame": "S",
                   "riservatoDocente": False, "prenotabileDa": "", "sessione": ""},
        }
        self._ids = itertools.count(9002)

    def teachings(self):
        visti = {(d["cdsId"], d["adId"], d["aaId"]) for d in self._items.values()}
        items = [{"adId": ad_id, "cdsId": cds_id, "aaId": aa_id,
                  "adDes": "Insegnamento di prova [mock]", "adCode": "MOCK",
                  "cdsDes": "Corso di prova [mock]"}
                 for cds_id, ad_id, aa_id in sorted(visti)]
        return {"items": items, "count": len(items)}

    def _vuoto(self, cds_id, ad_id, aa_id, tipo_prova):
        campi = {nome: {"value": "" if nome != "riservatoDocente" else False,
                       "type": "checkbox" if nome == "riservatoDocente" else "text",
                       "editable": nome in self._editable} for nome in self._editable}
        campi["verbalizzazione"] = {"value": "FWP", "type": "text", "editable": False,
                                    "readOnlyReason": "Valore imposto dall'ateneo."}
        campi["appLogId"] = {"value": "", "type": "hidden", "editable": False}
        return {"modalita": "nuovo", "campi": campi,
                "hidden": {"NEW_APP": "1", "CDS_ID": str(cds_id), "AD_ID": str(ad_id),
                          "AA_ID": str(aa_id), "TIPO_PROVA": tipo_prova}}

    def list(self, cds_id, ad_id, aa_id, visibility="all"):
        items = []
        for app_id, dati in self._items.items():
            if (dati["cdsId"], dati["adId"], dati["aaId"]) != (cds_id, ad_id, aa_id):
                continue
            items.append({
                "appId": app_id, "tipoProva": dati["tipoProva"],
                "descrizione": dati["descrizione"], "data": dati["dataAppello"],
                "ora": f"{dati['ora']}:{dati['minuti']}", "luogo": None, "badges": [],
                "iscrizioni": {"stato": {"code": "in_corso", "label": None}, "iscritti": 0},
                "esiti": {"stato": {"code": "non_previsto", "label": None}, "inseriti": 0},
                "verbali": {"stato": {"code": "non_previsto", "label": None}, "caricati": 0},
                "azioni": [{"kind": "modifica", "label": None}],
                "permessi": {"modificabile": True, "cancellabile": True, "haIscritti": False},
                "contesto": {"cdsId": cds_id, "adId": ad_id, "aaId": aa_id},
            })
        return {"contesto": {"insegnamento": "Insegnamento di prova [mock]",
                             "corsoDiStudio": "Corso di prova [mock]"},
                "items": items, "count": len(items)}

    def new_form(self, cds_id, ad_id, aa_id, exam_type="PF"):
        return self._vuoto(cds_id, ad_id, aa_id, exam_type)

    def edit_form(self, app_id, cds_id, ad_id, aa_id, exam_type="PF"):
        dati = self._items.get(int(app_id))
        if dati is None:
            raise NotFound("Appello non trovato (mock).")
        campi = self._vuoto(cds_id, ad_id, aa_id, exam_type)["campi"]
        for nome, valore in dati.items():
            if nome in campi:
                campi[nome]["value"] = valore
        return {"modalita": "modifica", "campi": campi,
                "hidden": {"NEW_APP": "0", "CDS_ID": str(cds_id), "AD_ID": str(ad_id),
                          "AA_ID": str(aa_id), "APP_ID": str(app_id),
                          "TIPO_PROVA": exam_type}}

    def save(self, form, patch, submit="save", notifications=None):
        sconosciuti = set(patch) - self._editable
        if sconosciuti:
            raise ValidationFailed(
                "Campi non modificabili o sconosciuti: " + ", ".join(sorted(sconosciuti)))
        attuali = {nome: campo.get("value") for nome, campo in form["campi"].items()}
        modello = {**attuali, **patch}
        mancanti = [nome for nome in self._required if modello.get(nome) in (None, "")]
        if mancanti:
            raise ValidationFailed("Campi obbligatori mancanti: " + ", ".join(sorted(mancanti)))

        hidden = form["hidden"]
        if form["modalita"] == "nuovo":
            app_id = next(self._ids)
        else:
            app_id = int(hidden["APP_ID"])
        self._items[app_id] = {
            "cdsId": int(hidden["CDS_ID"]), "adId": int(hidden["AD_ID"]),
            "aaId": int(hidden["AA_ID"]), "tipoProva": hidden.get("TIPO_PROVA", "PF"),
            **{k: v for k, v in modello.items() if k in self._editable}}
        return {"dryRun": False, "applied": True, "appello": modello, "appId": app_id}

    def delete(self, app_id, cds_id, ad_id, aa_id):
        if int(app_id) not in self._items:
            raise NotFound("Appello non trovato (mock).")
        del self._items[int(app_id)]
        return {"dryRun": False, "applied": True}

    def enrolled_students(self, app_id, cds_id, ad_id, aa_id):
        dati = self._items.get(int(app_id))
        if dati is None:
            raise NotFound("Appello non trovato (mock).")
        items = [
            {"numero": 1, "dataIscrizione": "2026-08-20", "matricola": "0120000001",
             "nominativo": "BIANCHI LUCA [mock]", "codiceAd": "MOCK",
             "dataNascita": "2000-05-14", "annoFrequenza": "2025/2026",
             "cfu": "6", "esito": ""},
        ]
        return {"descrizioneAppello": dati["descrizione"],
                "dateAppello": f"{dati['dataAppello']} {dati['ora']}:{dati['minuti']}",
                "totaleIscritti": len(items), "items": items, "count": len(items)}

    def enrolled_students_pdf(self, app_id, cds_id, ad_id, aa_id) -> bytes:
        if int(app_id) not in self._items:
            raise NotFound("Appello non trovato (mock).")
        # PDF minimo ma valido, sufficiente per provare il download in app
        # senza generare davvero un documento con ReportLab/simili.
        return (b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]>>endobj\n"
                b"trailer<</Root 1 0 R>>")


class MockGraduationAdapter:
    """Simula la pagina "Laureandi assegnati": stessa forma dei dati reali
    (matricola/nominativo/ruoloDocente/...), per sviluppare e provare la UI
    docente senza credenziali reali."""

    def theses(self):
        items = [
            {"matricola": "0124001111", "nominativo": "ROSSI MARIO",
             "ruoloDocente": "Primo relatore", "dataApprovazioneTesi": "2026-05-10",
             "sessioneLaurea": "Sessione Anticipata ed Estiva (A.A. 2025/2026) [mock]",
             "dataAppello": "2026-07-24", "appello": "Appello di prova [mock]",
             "statoTesi": "Approvata", "dataAssegnazioneTesi": "2026-01-15",
             "corso": {"cod": "0124", "des": "INFORMATICA [mock]",
                      "tipo": "Corso di Laurea Triennale"},
             "tesiId": 1, "persId": 1, "domCtId": 1},
        ]
        return {"items": items, "count": len(items)}


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

    def open_web_calendar(self, settings):
        """Stesso nome di metodo dell'adapter reale: nessuna ramificazione
        nelle rotte. In mock non serve ESSE3_WEB_BASE, ne' rete."""
        return MockWebCalendarAdapter()

    def open_graduation(self, settings):
        return MockGraduationAdapter()

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

    # -- esiti del libretto ------------------------------------------------------
    _RAW_OUTCOMES = {
        91001: {"stato": "SUP", "esitoFinale": 28, "lodeFlg": False,
               "dataEsame": "2026-06-10", "docente": "Rossi"},
        91002: {"stato": "P"},
    }

    def get_exam_outcomes_batch(self, career, adsce_ids: list[int],
                                workers: int | None = None):
        outcomes, errors = {}, {}
        for adsce_id in adsce_ids:
            raw = self._RAW_OUTCOMES.get(adsce_id)
            if raw is None:
                errors[adsce_id] = {"status": 404,
                                    "message": "Nessun esito mock per questo adsceId."}
                continue
            outcome = mappers.map_exam_outcome(raw)
            if outcome is not None:
                outcomes[adsce_id] = outcome
        return outcomes, errors

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
