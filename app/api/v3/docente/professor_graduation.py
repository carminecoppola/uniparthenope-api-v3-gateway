"""Tesi assegnate al docente (relatore/tutor/correlatore) — sola lettura.

Stessa area web del Calendario Esami: login SSO lazy alla prima chiamata,
riusato per tutta la sessione (vedi professor_exams.py per i dettagli).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ....core.errors import SessionExpired
from ....core.security import Session
from ..routes import get_session

router = APIRouter(tags=["laureandi-docente"])


def _apri_graduation(request: Request, sessione: Session):
    adapter_tesi = sessione.data.get("graduation")
    if adapter_tesi is not None:
        return adapter_tesi

    adapter = sessione.data.get("adapter")
    if adapter is None:
        raise SessionExpired("Sessione senza adapter: eseguire di nuovo il login.")

    adapter_tesi = adapter.open_graduation(request.app.state.settings)
    sessione.data["graduation"] = adapter_tesi
    return adapter_tesi


@router.get("/professors/me/theses")
def elenco_tesi(request: Request, sessione: Session = Depends(get_session)):
    """Tesi di laurea/dottorato assegnate al docente, su tutti i corsi di
    studio in cui compare come relatore/correlatore/tutor."""
    try:
        return _apri_graduation(request, sessione).theses()
    except SessionExpired:
        sessione.data.pop("graduation", None)
        return _apri_graduation(request, sessione).theses()
