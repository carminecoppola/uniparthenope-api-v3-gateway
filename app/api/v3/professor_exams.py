"""Endpoint HTTP per la gestione degli appelli d'esame del docente.

Scrive dati reali su ESSE3 (creazione/modifica appelli): a differenza del
resto della v3, qui non si passa dall'e3rest (sola lettura) ma dall'area WEB
del Calendario Esami, con un login aggiuntivo (stesse credenziali, cookie
JSESSIONID) eseguito alla PRIMA chiamata docente della sessione — chi non
tocca mai queste rotte non paga il costo di un secondo login. Il cookie
resta nella sessione del server e non viene mai restituito al client.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ...core.errors import SessionExpired
from ...core.security import Session
from .routes import get_session

router = APIRouter(tags=["appelli-docente"])


class DatiAppello(BaseModel):
    """Corpo delle richieste di creazione/modifica.

    - cdsId, adId, aaId: identificano corso di studio, insegnamento e anno.
    - tipoProva: "PF" (appello) o "PP" (prova parziale).
    - appello: campi da salvare (data, ora, aula, note, ...).
    - submit: "save" oppure "saveAndAdd".
    - notifiche: comunicazioni opzionali agli iscritti in caso di modifica.
    """

    cdsId: int
    adId: int
    aaId: int
    tipoProva: str = "PF"
    appello: dict
    submit: str = "save"
    notifiche: dict | None = None


def _apri_calendario(request: Request, sessione: Session):
    """Recupera (o apre) l'adapter del Calendario Esami per la sessione.

    Riusa il cookie JSESSIONID finché è valido; se `open_web_calendar` non è
    disponibile sull'adapter (non dovrebbe accadere: sia l'adapter reale sia
    quello mock lo implementano) la sessione va rifatta da capo.
    """
    calendario = sessione.data.get("web_calendar")
    if calendario is not None:
        return calendario

    adapter = sessione.data.get("adapter")
    if adapter is None:
        raise SessionExpired("Sessione senza adapter: eseguire di nuovo il login.")

    calendario = adapter.open_web_calendar(request.app.state.settings)
    sessione.data["web_calendar"] = calendario
    return calendario


def _con_calendario(request: Request, sessione: Session, azione):
    """Esegue `azione(calendario)`; se il cookie web è scaduto (sessione
    separata da quella REST/Bearer) rifà il login web una volta e riprova."""
    calendario = _apri_calendario(request, sessione)
    try:
        return azione(calendario)
    except SessionExpired:
        sessione.data.pop("web_calendar", None)
        calendario = _apri_calendario(request, sessione)
        return azione(calendario)


@router.get("/professors/me/teachings")
def elenco_insegnamenti(request: Request, sessione: Session = Depends(get_session)):
    """Insegnamenti del docente su tutti gli anni accademici, con cdsId/adId/
    aaId già pronti per /professors/me/exam-sessions.

    A differenza della vecchia API v1 `professor/getCourses/{aaId}` (che va
    interrogata con l'anno "giusto", non sempre quello restituito dalla
    sessione — a inizio anno accademico la nuova didattica non è ancora
    pubblicata lì), questa proviene dalla pagina "Lista Attività" di ESSE3,
    che elenca ogni insegnamento già abbinato al proprio aaId corretto.
    """
    return _con_calendario(request, sessione, lambda c: c.teachings())


@router.get("/professors/me/exam-sessions")
def elenco_appelli(
    cdsId: int,
    adId: int,
    aaId: int,
    request: Request,
    visibility: str = "all",
    sessione: Session = Depends(get_session),
):
    """Restituisce gli appelli dell'insegnamento indicato.

    Il parametro visibility permette di limitare il risultato agli appelli
    passati o futuri.
    """
    return _con_calendario(request, sessione,
                           lambda c: c.list(cdsId, adId, aaId, visibility))


@router.post("/professors/me/exam-sessions", status_code=201)
def crea_appello(
    dati: DatiAppello,
    request: Request,
    sessione: Session = Depends(get_session),
):
    """Registra un nuovo appello o una nuova prova parziale.

    Prima viene letto il modulo vuoto fornito da ESSE3, così da conoscere i
    campi e le opzioni ammesse; poi i dati ricevuti vengono controllati e
    salvati (o solo validati, se ESSE3_WEB_DRY_RUN_WRITES è attivo).
    """

    def azione(calendario):
        modulo = calendario.new_form(dati.cdsId, dati.adId, dati.aaId, dati.tipoProva.upper())
        return calendario.save(modulo, dati.appello, dati.submit, dati.notifiche)

    return _con_calendario(request, sessione, azione)


@router.patch("/professors/me/exam-sessions/{app_id}")
def modifica_appello(
    app_id: int,
    dati: DatiAppello,
    request: Request,
    sessione: Session = Depends(get_session),
):
    """Aggiorna un appello esistente.

    Viene letto il modulo con i valori attuali e vengono sostituiti solo i
    campi presenti nella richiesta: tutti gli altri restano invariati.
    """

    def azione(calendario):
        modulo = calendario.edit_form(app_id, dati.cdsId, dati.adId, dati.aaId,
                                      dati.tipoProva.upper())
        risultato = calendario.save(modulo, dati.appello, dati.submit, dati.notifiche)
        return {"appId": app_id, **risultato}

    return _con_calendario(request, sessione, azione)
