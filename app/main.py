"""Applicazione FastAPI: middleware X-Request-Id, errori RFC 9457, wiring."""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api.v3.routes import router
from .api.v3.upstream import register_upstream_routes
from .core.cache import TTLCache
from .core.config import settings
from .core.errors import ApiError
from .core.ratelimit import TokenBucket
from .core.security import SessionStore

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


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

    app.include_router(router, prefix="/v3")
    register_upstream_routes(app)
    return app


app = create_app()
