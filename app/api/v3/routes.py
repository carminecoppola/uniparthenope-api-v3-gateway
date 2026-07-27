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

from ...core.errors import RateLimited, SessionExpired, ValidationFailed
from ...core.security import Session
from ...domain.booking import BookingService

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
    return BookingService(_adapter(session),
                          plan_cache=request.app.state.plan_cache,
                          plan_ttl_s=request.app.state.settings.plan_ttl_s)


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


# ---------------------------------------------------------------- auth

@router.post("/auth/sessions", status_code=201, tags=["auth"])
def create_session(body: LoginBody, request: Request):
    """Login: ESSE3 viene interrogato UNA volta; poi si vive di token."""
    ip = request.client.host if request.client else "unknown"
    allowed, retry = request.app.state.login_bucket.allow(f"{body.username}|{ip}")
    if not allowed:
        raise RateLimited(retry, "Troppi tentativi di accesso: riprovare più tardi.")
    profile, careers, adapter = request.app.state.do_login(body.username, body.password)
    active = next((c for c in careers if c.active), careers[0])
    tokens = request.app.state.sessions.create(
        body.username, careers, active.career_id,
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
def my_plan(request: Request, session: Session = Depends(get_session)):
    entries = _booking(request, session).plan(session.career_id)
    return {"items": [asdict(e) for e in entries], "count": len(entries)}


@router.get("/students/me/reservations", tags=["students"])
def my_reservations(session: Session = Depends(get_session)):
    reservations, _skipped = _adapter(session).get_reservations(_career(session))
    return {"items": [asdict(r) for r in reservations], "count": len(reservations)}


# ---------------------------------------------------------------- appelli

@router.get("/exam-sessions", tags=["exams"])
def exam_sessions(request: Request, adId: int | None = None,
                  bookable: bool | None = None,
                  session: Session = Depends(get_session)):
    """Elenco appelli con `bookable` risolto LATO SERVER (mai euristiche UI)."""
    svc = _booking(request, session)
    career = _career(session)
    sessions = svc.exam_sessions(career, ad_id=adId)
    plan_ids = {e.ad_id for e in svc.plan(career.career_id)}
    items = []
    for s in sessions:
        if bookable is not None and s.bookable != bookable:
            continue
        item = asdict(s)
        item["inPlan"] = s.ad_id in plan_ids
        items.append(item)
    return {"items": items, "count": len(items)}


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
