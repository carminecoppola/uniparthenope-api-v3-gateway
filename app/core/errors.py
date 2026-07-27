"""Modello errori RFC 9457 (application/problem+json).

Ogni errore ha: status HTTP corretto, `code` stabile leggibile a macchina,
`type` URI, `detail` umano, `requestId` per correlare i log. Mai stack trace
al client, mai 200 che nasconde un errore, mai 500 per input dell'utente.
"""
from __future__ import annotations

BASE_TYPE = "https://api.uniparthenope.example/errors/"


class ApiError(Exception):
    status: int = 500
    code: str = "internal_error"
    title: str = "Errore interno"

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.title)
        self.detail = detail

    def problem(self, request_id: str | None = None) -> dict:
        doc: dict = {
            "type": BASE_TYPE + self.code,
            "title": self.title,
            "status": self.status,
            "code": self.code,
        }
        if self.detail:
            doc["detail"] = self.detail
        doc["requestId"] = request_id
        return doc


# ----------------------------------------------------------------- 4xx client

class AuthRequired(ApiError):
    status, code, title = 401, "auth_required", "Autenticazione richiesta"


class InvalidCredentials(ApiError):
    status, code, title = 401, "invalid_credentials", "Credenziali non valide"


class SessionExpired(ApiError):
    status, code, title = 401, "session_expired", "Sessione scaduta o revocata"


class Forbidden(ApiError):
    status, code, title = 403, "forbidden", "Operazione non consentita"


class ApiKeyRequired(ApiError):
    status, code, title = 401, "api_key_required", "API key richiesta"


class InvalidApiKey(ApiError):
    status, code, title = 401, "invalid_api_key", "API key non valida o revocata"


class NotFound(ApiError):
    status, code, title = 404, "not_found", "Risorsa non trovata"


class Conflict(ApiError):
    status, code, title = 409, "conflict", "Conflitto con lo stato attuale"


class ValidationFailed(ApiError):
    status, code, title = 400, "validation_failed", "Richiesta non valida"


class PlanEntryNotFound(ApiError):
    """Fix PRB-12: adsceId non risolvibile dal libretto → 422 di dominio,
    MAI un None inoltrato all'upstream."""
    status, code, title = 422, "plan_entry_not_found", "Insegnamento non nel piano di studi"


class RateLimited(ApiError):
    status, code, title = 429, "rate_limited", "Troppe richieste"

    def __init__(self, retry_after: int, detail: str = "") -> None:
        super().__init__(detail)
        self.retry_after = max(1, int(retry_after))

    def problem(self, request_id: str | None = None) -> dict:
        doc = super().problem(request_id)
        doc["retryAfter"] = self.retry_after
        return doc


# ----------------------------------------------------------------- 5xx upstream

class UpstreamContract(ApiError):
    """L'upstream ha risposto qualcosa che viola il contratto atteso."""
    status, code, title = 502, "upstream_contract", "Risposta upstream non conforme"


class UpstreamUnavailable(ApiError):
    status, code, title = 503, "upstream_unavailable", "Servizio upstream non disponibile"


class UpstreamNotConfigured(ApiError):
    """Percorso upstream reale non ancora configurato/verificato: onestà,
    non un finto 200."""
    status, code, title = 503, "upstream_path_not_configured", "Percorso upstream non configurato"


class UpstreamTimeout(ApiError):
    status, code, title = 504, "upstream_timeout", "Timeout verso l'upstream"
