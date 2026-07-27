"""Applicazione FastAPI: middleware X-Request-Id, errori RFC 9457, wiring."""
from __future__ import annotations

import logging
import logging.handlers
import os
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from .api.v3.routes import router
from .api.v3.upstream import register_upstream_routes
from .core.apikeys import ApiKeyStore
from .core.cache import TTLCache
from .core.config import settings
from .core.errors import ApiError
from .core.ratelimit import TokenBucket
from .core.security import SessionStore

# Percorsi raggiungibili senza API key: documentazione pubblica (richiesta
# del prof: le API restano sempre pubbliche/documentate) + l'endpoint per
# richiederne una. Tutto il resto richiede 'X-API-Key'.
_API_KEY_EXEMPT_PATHS = {
    "/v3/docs", "/v3/openapi.json", "/v3/redoc",
    "/v3/api-keys", "/v3/health",
}

# Solo per far comparire il bottone "Authorize" su /v3/docs: l'enforcement
# vero resta nel middleware sotto (auto_error=False, questa dipendenza da
# sola non blocca nulla).
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False,
                              description="Richiedine una con POST /v3/api-keys")

def _configure_logging() -> None:
    """Tutto in una cartella logs/ dedicata (LOG_DIR override-abile), con
    rotazione automatica: niente più file che crescono all'infinito (fix
    dello stesso problema visto con src.bin sul sistema legacy), e facile
    da recuperare per il debug ('logs/app.log' + backup .1, .2, ...)."""
    log_dir = Path(os.environ.get("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


_configure_logging()


def create_app() -> FastAPI:
    app = FastAPI(
        title="UniParthenope API v3 — gateway",
        version="3.0.0",
        description=("Gateway proprio davanti alle API ufficiali v1/v2. "
                     "Errori RFC 9457, sessioni con token, cache, circuit breaker."),
        docs_url="/v3/docs", openapi_url="/v3/openapi.json")

    app.state.settings = settings
    app.state.sessions = SessionStore(settings.access_ttl_s, settings.refresh_ttl_s)
    app.state.login_bucket = TokenBucket(capacity=settings.login_rate_per_min)
    app.state.cache = TTLCache()
    app.state.plan_cache = TTLCache()
    app.state.api_keys = ApiKeyStore()

    if settings.mock_esse3:
        from .adapters.esse3.mock import MockEsse3Adapter
        shared = MockEsse3Adapter()
        app.state.public_adapter = shared
        app.state.upstream_transport = None

        def do_login(username: str, password: str):
            profile, careers = shared.login(username, password)
            return profile, careers, shared
    else:
        from .adapters.esse3.client import Esse3Adapter, Esse3Transport
        transport = Esse3Transport(settings.upstream_base,
                                   settings.upstream_timeout_s, settings)
        app.state.public_adapter = Esse3Adapter(transport, None, None)
        app.state.upstream_transport = transport

        def do_login(username: str, password: str):
            adapter = Esse3Adapter(transport, username, password)
            profile, careers = adapter.login()
            adapter.set_career_context(careers)
            return profile, careers, adapter

    app.state.do_login = do_login

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next):
        path = request.url.path
        if path in _API_KEY_EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        try:
            raw_key = request.headers.get("X-API-Key")
            record = request.app.state.api_keys.touch_and_check(raw_key)
        except ApiError as exc:
            # Middleware esterno all'ExceptionMiddleware di Starlette: gli
            # errori qui non passerebbero dagli @app.exception_handler, quindi
            # costruiamo qui stesso la stessa risposta RFC 9457.
            request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
            return JSONResponse(status_code=exc.status,
                                content=exc.problem(request_id),
                                media_type="application/problem+json")
        request.state.api_key_owner = record.owner
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        request_id = getattr(request.state, "request_id", None)
        headers = {}
        if getattr(exc, "retry_after", None):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.status,
                            content=exc.problem(request_id),
                            media_type="application/problem+json",
                            headers=headers)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        # Mai stack trace al client: log correlato via requestId.
        request_id = getattr(request.state, "request_id", None)
        logging.getLogger("v3").exception("Errore non gestito (requestId=%s)", request_id)
        return JSONResponse(status_code=500, content={
            "type": "https://api.uniparthenope.example/errors/internal_error",
            "title": "Errore interno", "status": 500,
            "code": "internal_error", "requestId": request_id,
        }, media_type="application/problem+json")

    app.include_router(router, prefix="/v3", dependencies=[Depends(api_key_scheme)])
    register_upstream_routes(app, api_key_dependency=Depends(api_key_scheme))
    return app


app = create_app()
