"""Rotte /v3 — contratto: sostantivi plurali, errori RFC 9457, ID opachi.

Copertura delle sette funzioni della matrice di parità (§13.2 audit):
appelli, prenotazione (fix adsceId), cancellazione (idempotente + dryRun),
foto (reintrodotta e migliorata), dispositivi/notifiche, autobus, mense.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...core.errors import (PlanEntryNotFound, RateLimited, SessionExpired,
                            ValidationFailed)
from ...core.security import Session
from ...domain.booking import BookingService, filter_entries

router = APIRouter()


# ---------------------------------------------------------------- dipendenze

def get_session(request: Request) -> Session:
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    return request.app.state.sessions.resolve_access(token)


def _adapter(session: Session):
    adapter = session.data.get("adapter")
    if adapter is None:
        raise SessionExpired("Sessione senza adapter: eseguire di nuovo il login.")
    return adapter


def _career(session: Session):
    for career in session.careers:
        if career.career_id == session.career_id:
            return career
    raise ValidationFailed("Carriera attiva non trovata nella sessione.")


def _booking(request: Request, session: Session) -> BookingService:
    settings = request.app.state.settings
    return BookingService(
        _adapter(session), plan_cache=request.app.state.plan_cache,
        plan_ttl_s=settings.plan_ttl_s,
        outcome_ttl_s=getattr(settings, "plan_outcome_ttl_s", 900),
        outcome_passed_ttl_s=getattr(settings, "plan_outcome_passed_ttl_s", 86_400),
        outcome_workers=getattr(settings, "plan_outcome_workers", 8))


# ---------------------------------------------------------------- modelli I/O

class LoginBody(BaseModel):
    username: str
    password: str


class RefreshBody(BaseModel):
    refreshToken: str


class BookBody(BaseModel):
    adId: int
    aaOffId: int | None = None


class DeviceBody(BaseModel):
    platform: str = "unknown"


class ApiKeyRequestBody(BaseModel):
    owner: str   # nome persona/app/team richiedente, solo per tracciabilità


# ---------------------------------------------------------------- api key

@router.post("/api-keys", status_code=201, tags=["api-keys"])
def request_api_key(body: ApiKeyRequestBody, request: Request):
    """Richiesta pubblica e self-service di una API key (nessuna approvazione
    manuale, come OpenTopography): l'API resta pubblica e documentata, ma
    ogni chiamata successiva deve portare la chiave in 'X-API-Key'."""
    if not body.owner.strip():
        raise ValidationFailed("Il campo 'owner' non può essere vuoto.")
    key = request.app.state.api_keys.issue(body.owner.strip())
    return {"apiKey": key, "owner": body.owner.strip(),
            "usage": "Aggiungi l'header 'X-API-Key: <apiKey>' ad ogni richiesta."}


# ---------------------------------------------------------------- auth

@router.post("/auth/sessions", status_code=201, tags=["auth"])
def create_session(body: LoginBody, request: Request):
    """Login: ESSE3 viene interrogato UNA volta; poi si vive di token."""
    ip = request.client.host if request.client else "unknown"
    allowed, retry = request.app.state.login_bucket.allow(f"{body.username}|{ip}")
    if not allowed:
        raise RateLimited(retry, "Troppi tentativi di accesso: riprovare più tardi.")
    profile, careers, adapter = request.app.state.do_login(body.username, body.password)
    # Un docente puro non ha carriera studente: career_id resta None, le
    # rotte studente falliranno con un 400 chiaro via _career() invece di
    # un IndexError qui.
    active = next((c for c in careers if c.active), careers[0] if careers else None)
    tokens = request.app.state.sessions.create(
        body.username, careers, active.career_id if active else None,
        data={"adapter": adapter, "profile": profile})
    return {**tokens, "profile": profile, "careers": [asdict(c) for c in careers]}


@router.post("/auth/sessions/refresh", tags=["auth"])
def refresh_session(body: RefreshBody, request: Request):
    return request.app.state.sessions.refresh(body.refreshToken)


@router.delete("/auth/sessions", status_code=204, tags=["auth"])
def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    request.app.state.sessions.logout_by_access(token)
    return Response(status_code=204)


# ---------------------------------------------------------------- studente

@router.get("/students/me", tags=["students"])
def me(session: Session = Depends(get_session)):
    return {"username": session.username,
            "activeCareerId": session.career_id,
            "careers": [asdict(c) for c in session.careers]}


@router.get("/students/me/plan", tags=["students"])
def my_plan(request: Request, session: Session = Depends(get_session),
           withOutcomes: bool = True, anno: int | None = None,
           semestre: str | None = None, stato: str | None = None,
           workers: int | None = None):
    """Piano di studi con stato/voto/crediti per insegnamento.

    Gli esiti mancanti vengono letti tutti insieme in una sola attesa
    invece che uno alla volta (schermata Corsi altrimenti lenta con
    carriere piene): vedi BookingService.complete_outcomes. Un
    insegnamento il cui esito non arriva resta comunque nell'elenco,
    senza esito, con il motivo in `errors`.
    """
    svc = _booking(request, session)
    career = _career(session)
    if withOutcomes:
        entries, stats, errors = svc.plan_with_outcomes(career, workers=workers)
    else:
        entries = svc.plan(session.career_id)
        stats, errors = {"giaNelLibretto": len(entries), "daMemoria": 0,
                         "letteAdesso": 0}, {}

    selected = filter_entries(entries, anno=anno, semestre=semestre, stato=stato)

    result = {"items": [asdict(e) for e in selected], "count": len(selected),
              "totaleLibretto": len(entries), "letture": stats}
    if errors:
        result["errors"] = {str(k): v for k, v in errors.items()}
    return result


@router.get("/students/me/plan-summary", tags=["students"])
def plan_summary(request: Request, session: Session = Depends(get_session),
                 workers: int | None = None):
    """Crediti acquisiti, esami superati e medie — nessuna attesa in più
    rispetto all'elenco: usa gli stessi dati già completati."""
    return _booking(request, session).plan_summary(_career(session), workers=workers)


@router.get("/students/me/plan/{adsce_id}", tags=["students"])
def plan_entry_detail(adsce_id: int, request: Request,
                      session: Session = Depends(get_session),
                      workers: int | None = None):
    """Un solo insegnamento del libretto, completo di esito."""
    result = _booking(request, session).entry_detail(
        _career(session), adsce_id, workers=workers)
    if result is None:
        raise PlanEntryNotFound(
            f"Nessun insegnamento con adsceId {adsce_id} nel libretto.")
    entry, errors = result
    payload = asdict(entry)
    if errors:
        payload["errors"] = {str(k): v for k, v in errors.items()}
    return payload


@router.post("/students/me/plan/{adsce_id}/refresh", tags=["students"])
def plan_entry_refresh(adsce_id: int, request: Request,
                       session: Session = Depends(get_session)):
    """Rilegge l'esito di un solo insegnamento, dimenticando solo quello."""
    result = _booking(request, session).refresh_entry(_career(session), adsce_id)
    if result is None:
        raise PlanEntryNotFound(
            f"Nessun insegnamento con adsceId {adsce_id} nel libretto.")
    entry, errors = result
    payload = asdict(entry)
    if errors:
        payload["errors"] = {str(k): v for k, v in errors.items()}
    return payload


@router.get("/students/me/reservations", tags=["students"])
def my_reservations(session: Session = Depends(get_session)):
    reservations, _skipped = _adapter(session).get_reservations(_career(session))
    return {"items": [asdict(r) for r in reservations], "count": len(reservations)}


# ---------------------------------------------------------------- appelli

@router.get("/exam-sessions", tags=["exams"])
def exam_sessions(request: Request, adId: int | None = None,
                  adIds: str | None = None, workers: int | None = None,
                  bookable: bool | None = None,
                  session: Session = Depends(get_session)):
    """Elenco appelli con `bookable` risolto LATO SERVER (mai euristiche UI).

    Senza parametri: TUTTI gli appelli del piano di studi della carriera
    attiva, in una sola chiamata — il gateway legge da solo gli `adId` dal
    libretto e li interroga in batch, il client non deve più fare il giro
    "prima /students/me/plan poi /exam-sessions?adIds=...".

    `adId` interroga un solo insegnamento (tutte le pagine, non solo la
    prima). `adIds` (comma-separated) ne interroga più di uno in parallelo
    lato server — `workers` sceglie quanti insieme (default e cap lato
    server, vedi APPELLI_WORKERS/APPELLI_MAX_WORKERS): il client NON deve
    fare il proprio parallelismo se usa `adIds`, lo fa già il gateway.
    Un adId fallito (dentro `adIds` o nel caso senza parametri) non fa
    fallire gli altri: risulta in `errors` invece che interrompere la
    risposta.
    """
    svc = _booking(request, session)
    career = _career(session)
    plan_ids = {e.ad_id for e in svc.plan(career.career_id)}
    errors: dict[str, str] = {}

    if adIds:
        ad_id_list = [int(x) for x in adIds.split(",") if x.strip().isdigit()]
        if not ad_id_list:
            raise ValidationFailed("adIds non contiene alcun identificatore valido.")
        sessions, errori_ad = svc.exam_sessions_batch(career, ad_id_list, workers=workers)
        errors = {str(k): v for k, v in errori_ad.items()}
    elif adId is not None:
        sessions = svc.exam_sessions(career, ad_id=adId)
    else:
        # Nessun parametro: batch automatico su tutti gli adId del piano.
        if not plan_ids:
            sessions = []
        else:
            sessions, errori_ad = svc.exam_sessions_batch(
                career, sorted(plan_ids), workers=workers)
            errors = {str(k): v for k, v in errori_ad.items()}

    items = []
    for s in sessions:
        if bookable is not None and s.bookable != bookable:
            continue
        item = asdict(s)
        item["inPlan"] = s.ad_id in plan_ids
        items.append(item)

    result = {"items": items, "count": len(items)}
    if errors:
        result["errors"] = errors
    return result


@router.post("/exam-sessions/{app_id}/reservations", status_code=201, tags=["exams"])
def book_exam(app_id: int, body: BookBody, request: Request, dryRun: bool = False,
              session: Session = Depends(get_session)):
    """Prenotazione con fix PRB-12: adsceId risolto dal libretto o 422."""
    result = _booking(request, session).book(
        _career(session), app_id=app_id, ad_id=body.adId,
        aa_off_id=body.aaOffId, dry_run=dryRun)
    if dryRun:
        return JSONResponse(status_code=200, content=result)
    return result


@router.delete("/reservations/{reservation_id}", tags=["exams"])
def cancel_reservation(reservation_id: str, request: Request, dryRun: bool = False,
                       session: Session = Depends(get_session)):
    """Cancellazione idempotente (PRB-14): la seconda volta è comunque 204."""
    result = _booking(request, session).cancel(
        _career(session), reservation_id, dry_run=dryRun)
    if dryRun:
        return JSONResponse(status_code=200, content=result)
    return Response(status_code=204,
                    headers={"X-Already-Gone": str(result["alreadyGone"]).lower()})


# ---------------------------------------------------------------- foto (PRB-13)

def _photo_response(request: Request, session: Session, kind: str, ref, size: int):
    if size not in (48, 128, 512):
        raise ValidationFailed("size ammessi: 48, 128, 512.")
    data = _adapter(session).get_photo(kind, ref)  # NotFound → 404 problem+json
    accept = request.headers.get("Accept", "")
    data, media_type = _maybe_resize(data, size, accept)
    etag = 'W/"' + hashlib.sha256(data).hexdigest()[:16] + '"'
    headers = {"Cache-Control": "private, max-age=86400",
               "Vary": "Accept", "ETag": etag}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type=media_type, headers=headers)


def _maybe_resize(data: bytes, size: int, accept: str):
    """Ridimensiona server-side e negozia WebP. Se Pillow manca, originale."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.thumbnail((size, size))
        want_webp = "image/webp" in accept
        buf = io.BytesIO()
        img.save(buf, format="WEBP" if want_webp else "PNG")
        return buf.getvalue(), ("image/webp" if want_webp else "image/png")
    except Exception:
        return data, "image/png"


@router.get("/students/me/photo", tags=["photos"])
def my_photo(request: Request, size: int = 128,
             session: Session = Depends(get_session)):
    profile = session.data.get("profile", {})
    ref = profile.get("personId") or profile.get("persId") or session.username
    return _photo_response(request, session, "student", ref, size)


@router.get("/professors/{professor_ref}/photo", tags=["photos"])
def professor_photo(professor_ref: str, request: Request, size: int = 128,
                    session: Session = Depends(get_session)):
    # professor_ref è un identificatore OPACO: mai ID sequenziali enumerabili.
    return _photo_response(request, session, "professor", professor_ref, size)


# ---------------------------------------------------------------- dispositivi (PRB-15)

@router.put("/devices/{token}", status_code=204, tags=["devices"])
def register_device(token: str, request: Request, body: DeviceBody | None = None,
                    session: Session = Depends(get_session)):
    """Registrazione idempotente, legata alla sessione (mai username in chiaro)."""
    platform = body.platform if body else "unknown"
    _adapter(session).register_device(session.username, token, platform)
    return Response(status_code=204)


@router.delete("/devices/{token}", status_code=204, tags=["devices"])
def unregister_device(token: str, session: Session = Depends(get_session)):
    _adapter(session).unregister_device(token)
    return Response(status_code=204)


# ---------------------------------------------------------------- autobus / mense (PRB-16)

@router.get("/transport/bus/routes", tags=["services"])
def bus_routes(request: Request, sede: str = "1"):
    """Pubblico (anche ospiti). Cache + stale-while-revalidate."""
    state = request.app.state
    value, stale = state.cache.get_or_load(
        ("bus_routes", sede), lambda: state.public_adapter.bus_routes(sede),
        ttl=state.settings.bus_ttl_s, stale_ttl=86400)
    return JSONResponse({"items": value, "stale": stale},
                        headers={"X-Data-Stale": str(stale).lower()})


@router.get("/dining/menus", tags=["services"])
def dining_menus(request: Request, date: str | None = None):
    state = request.app.state
    value, stale = state.cache.get_or_load(
        ("dining", date), lambda: state.public_adapter.dining_menus(date),
        ttl=state.settings.dining_ttl_s, stale_ttl=86400)
    return JSONResponse({"items": value, "stale": stale},
                        headers={"X-Data-Stale": str(stale).lower()})


# ---------------------------------------------------------------- health

@router.get("/health", tags=["health"])
def health(request: Request):
    settings = request.app.state.settings
    return {"status": "ok",
            "mode": "mock" if settings.mock_esse3 else "esse3",
            "time": datetime.now(timezone.utc).isoformat()}


from .docente.professor_exams import router as professor_exams_router
from .docente.professor_graduation import router as professor_graduation_router
from .pta import router as pta_router

router.include_router(professor_exams_router)
router.include_router(professor_graduation_router)
router.include_router(pta_router)
