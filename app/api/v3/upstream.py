"""Gateway completo delle API pubblicate in swagger.json.

Espone ogni operazione upstream sotto ``/v3/upstream`` mantenendo metodo,
percorso, query string, body, status, media type e file binari. Il catalogo e'
generato dalla spec inclusa nel pacchetto: non e' un open proxy e non puo'
inoltrare percorsi assenti dallo Swagger.

Autenticazione:
- API pubbliche: nessun token;
- API protette: Bearer della sessione v3 (consigliato), oppure Basic per la
  migrazione del solo client legacy. L'header Basic non viene mai registrato.

Le GET pubbliche usano cache TTL + stale-on-error. POST/PUT/PATCH/DELETE non
sono mai ritentate o memorizzate automaticamente.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import Request, Response
from starlette.concurrency import run_in_threadpool

from ...core.errors import AuthRequired, RateLimited, UpstreamNotConfigured

_CATALOG_PATH = Path(__file__).with_name("upstream_catalog.json")
CATALOG = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))

# Percorsi legacy di login: sfruttabili per brute-force se non limitati,
# esattamente come sul sistema originale (audit di sicurezza pre-deploy).
# Inoltrati con lo stesso rate limiter usato da /v3/auth/sessions.
_LOGIN_PATHS = {"/UniparthenopeApp/v1/login", "/UniparthenopeApp/v2/login"}

# Header end-to-end sicuri da conservare. Gli hop-by-hop (Connection,
# Transfer-Encoding, Keep-Alive...) non devono attraversare un proxy.
_REQUEST_HEADERS = {"accept", "content-type", "if-none-match", "if-modified-since", "range"}
_RESPONSE_HEADERS = {
    "content-type", "content-length", "content-disposition", "etag",
    "last-modified", "cache-control", "expires", "retry-after",
    "accept-ranges", "content-range", "location",
}


class _ProxyResponseError(Exception):
    """Trasporta una risposta non-2xx senza permettere che venga messa in cache."""

    def __init__(self, result):
        super().__init__("upstream response is not cacheable")
        self.result = result


def _decode_basic(value: str) -> Optional[Tuple[str, str]]:
    if not value.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(value.split(None, 1)[1], validate=True).decode("utf-8")
        username, password = raw.split(":", 1)
        return username, password
    except Exception:
        raise AuthRequired("Header Basic non valido.")


def _upstream_auth(request: Request, protected: bool):
    if not protected:
        return None
    authorization = request.headers.get("Authorization", "")
    basic = _decode_basic(authorization)
    if basic is not None:
        return basic
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        session = request.app.state.sessions.resolve_access(token)
        adapter = session.data.get("adapter")
        auth = getattr(adapter, "upstream_auth", None)
        if auth is None:
            # In mock non esistono credenziali upstream: il proxy completo non
            # deve fingere di aver interrogato il sito reale.
            raise UpstreamNotConfigured(
                "Gateway upstream non disponibile in MOCK_ESSE3=1. Avviare la "
                "v3 reale oppure usare le rotte simulate documentate.")
        return auth
    raise AuthRequired(
        "API upstream protetta: usare Bearer v3 oppure Basic durante la migrazione.")


def _cache_ttl(settings, path: str) -> int:
    if path == "/GAUniparthenope/v1/getEvents":
        return settings.events_ttl_s
    if path.startswith("/Bus/"):
        return settings.bus_ttl_s
    if path.startswith("/Eating/"):
        return settings.dining_ttl_s
    # Contenuti pubblici generali: TTL corto, per non nascondere aggiornamenti.
    return 300


def _response_tuple(response):
    headers = {k: v for k, v in response.headers.items()
               if k.lower() in _RESPONSE_HEADERS}
    return response.status_code, headers, response.content


def _render(result, stale=False, expose_gateway_headers=True):
    status, headers, content = result
    headers = dict(headers)
    # Le rotte legacy alla radice devono conservare gli header upstream.
    # La diagnostica aggiuntiva e' esposta solo sul namespace opzionale /v3.
    if expose_gateway_headers:
        headers["X-Data-Stale"] = str(bool(stale)).lower()
    return Response(content=content, status_code=status, headers=headers)


def _login_rate_limit_key(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    basic = _decode_basic(request.headers.get("Authorization", ""))
    username = basic[0] if basic else "unknown"
    return f"{username}|{ip}"


async def _forward(request: Request, operation: Dict, legacy_root=False):
    transport = getattr(request.app.state, "upstream_transport", None)
    if transport is None:
        raise UpstreamNotConfigured(
            "Il proxy delle 91 operazioni richiede MOCK_ESSE3=0. In modalita' "
            "mock funzionano solo le facciate v3 simulate.")

    # Fix audit pre-deploy: il pass-through legacy del login non deve bypassare
    # il rate limiting applicato alla facciata /v3/auth/sessions, altrimenti
    # resta lo stesso vettore di brute-force del sistema originale.
    if operation["path"] in _LOGIN_PATHS:
        bucket = request.app.state.login_bucket
        allowed, retry = bucket.allow(_login_rate_limit_key(request))
        if not allowed:
            raise RateLimited(retry, "Troppi tentativi di accesso: riprovare più tardi.")

    auth = _upstream_auth(request, operation["protected"])
    body = await request.body()
    forwarded_headers = {
        k: v for k, v in request.headers.items() if k.lower() in _REQUEST_HEADERS
    }
    params = list(request.query_params.multi_items())
    path = operation["path"]
    for name, value in request.path_params.items():
        path = path.replace("{" + name + "}", str(value))

    def load():
        response = transport.request(
            operation["method"], path, auth=auth, params=params,
            content=body if body else None, headers=forwarded_headers,
            passthrough_5xx=legacy_root,
        )
        result = _response_tuple(response)
        if response.status_code < 200 or response.status_code >= 300:
            raise _ProxyResponseError(result)
        return result

    cacheable = operation["method"] == "GET" and not operation["protected"]
    if not cacheable:
        try:
            result = await run_in_threadpool(load)
        except _ProxyResponseError as exc:
            result = exc.result
        return _render(result, stale=False,
                       expose_gateway_headers=not legacy_root)

    cache_key = ("upstream", path, tuple(params), request.headers.get("Accept", ""))
    ttl = _cache_ttl(request.app.state.settings, operation["path"])
    try:
        result, stale = await run_in_threadpool(
            lambda: request.app.state.cache.get_or_load(
                cache_key, load, ttl=ttl, stale_ttl=max(ttl * 4, 86400)))
    except _ProxyResponseError as exc:
        result, stale = exc.result, False
    return _render(result, stale=stale,
                   expose_gateway_headers=not legacy_root)


def _factory(operation, legacy_root=False):
    async def endpoint(request: Request):
        return await _forward(request, operation, legacy_root=legacy_root)
    prefix = "legacy_" if legacy_root else "upstream_"
    endpoint.__name__ = prefix + operation["operationId"]
    endpoint.__doc__ = (
        operation.get("summary") or operation["operationId"]
    ) + ("\n\nInterfaccia legacy invariata; implementazione interna rifattorizzata."
         if legacy_root else
         "\n\nNamespace opzionale v3 dello stesso gateway upstream.")
    return endpoint


def register_upstream_routes(app, api_key_dependency=None) -> None:
    """Registra 91 rotte legacy IDENTICHE e il namespace v3 opzionale."""
    deps = [api_key_dependency] if api_key_dependency is not None else []
    for operation in CATALOG["operations"]:
        common = {
            "methods": [operation["method"]],
            "summary": operation.get("summary") or operation["operationId"],
            "response_class": Response,
            "dependencies": deps,
        }
        # Contratto richiesto dal professore: stesso path e stesso metodo.
        app.add_api_route(
            operation["path"],
            _factory(operation, legacy_root=True),
            tags=["legacy:" + operation["tag"]],
            operation_id="legacy_" + operation["operationId"],
            **common,
        )
        # Interfaccia migliorata/diagnostica mantenuta come opzione, non
        # necessaria al client esistente.
        app.add_api_route(
            "/v3/upstream" + operation["path"],
            _factory(operation, legacy_root=False),
            tags=["upstream:" + operation["tag"]],
            operation_id="upstream_" + operation["operationId"],
            **common,
        )

    async def catalog():
        return CATALOG

    app.add_api_route(
        "/v3/upstream-catalog", catalog, methods=["GET"],
        tags=["upstream:catalog"], operation_id="upstream_catalog",
        summary="Catalogo completo delle API upstream")
