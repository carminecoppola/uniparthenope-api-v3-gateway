"""Registro lezioni del docente (diario delle lezioni svolte) — sola lettura.

Stessa area web del Calendario Esami/Laureandi: login SSO lazy alla prima
chiamata, riusato per tutta la sessione (vedi professor_exams.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ...core.errors import SessionExpired
from ...core.security import Session
from .routes import get_session

router = APIRouter(tags=["registro-docente"])


def _apri_registro(request: Request, sessione: Session):
    adapter_registro = sessione.data.get("register")
    if adapter_registro is not None:
        return adapter_registro

    adapter = sessione.data.get("adapter")
    if adapter is None:
        raise SessionExpired("Sessione senza adapter: eseguire di nuovo il login.")

    adapter_registro = adapter.open_register(request.app.state.settings)
    sessione.data["register"] = adapter_registro
    return adapter_registro


def _con_registro(request: Request, sessione: Session, azione):
    try:
        return azione(_apri_registro(request, sessione))
    except SessionExpired:
        sessione.data.pop("register", None)
        return azione(_apri_registro(request, sessione))


@router.get("/professors/me/register/years")
def anni_registro(request: Request, sessione: Session = Depends(get_session)):
    """Anni accademici offerta per cui esiste un registro consultabile."""
    return _con_registro(request, sessione, lambda a: a.years())


@router.get("/professors/me/register")
def elenco_registri(
    request: Request,
    sessione: Session = Depends(get_session),
    aaOffId: int | None = Query(None, description="Anno accademico offerta"),
):
    """Registri (uno per insegnamento/partizione) dell'anno accademico
    indicato, o dell'anno correntemente selezionato lato ESSE3 se omesso."""
    return _con_registro(request, sessione, lambda a: a.list(aaOffId))


@router.get("/professors/me/register/{ad_log_id}")
def dettaglio_registro(
    ad_log_id: int,
    request: Request,
    sessione: Session = Depends(get_session),
    aaOffId: int = Query(..., description="Anno accademico offerta"),
    partCod: str = Query("S1", description="Codice partizione (da /register)"),
):
    """Lezioni inserite per un insegnamento: data, ore, titolo, tipo
    attività, più il riepilogo ore previste/inserite/mancanti."""
    return _con_registro(request, sessione,
                         lambda a: a.detail(ad_log_id, aaOffId, partCod))
