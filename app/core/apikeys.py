"""API key per l'accesso al gateway (richiesta del prof: API sempre
pubbliche/documentate, ma serve un processo di autorizzazione per usarle).

Modello preso da OpenTopography: richiesta self-service, nessuna approvazione
manuale, chiave restituita subito e da allegare ad ogni chiamata. Non è
autenticazione utente (quella resta /v3/auth/sessions) — identifica quale
applicazione/team sta chiamando, non quale persona.

Le chiavi sono salvate solo come hash SHA-256, stesso principio già usato
per i token di sessione: un dump della memoria non rivela chiavi spendibili.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class ApiKeyRecord:
    owner: str
    created_at: float
    revoked: bool = False
    request_count: int = 0


class ApiKeyStore:
    def __init__(self, time_fn=time.time) -> None:
        self._now = time_fn
        self._keys: dict[str, ApiKeyRecord] = {}   # sha256(key) -> record

    def issue(self, owner: str) -> str:
        raw = "upk_" + secrets.token_urlsafe(32)   # prefisso: riconoscibile nei log/diff
        self._keys[_hash(raw)] = ApiKeyRecord(owner=owner, created_at=self._now())
        return raw

    def touch_and_check(self, raw_key: str | None) -> ApiKeyRecord:
        from .errors import ApiKeyRequired, InvalidApiKey
        if not raw_key:
            raise ApiKeyRequired(
                "Header 'X-API-Key' richiesto. Richiedine una con POST /v3/api-keys.")
        record = self._keys.get(_hash(raw_key))
        if record is None or record.revoked:
            raise InvalidApiKey("Chiave non riconosciuta o revocata.")
        record.request_count += 1
        return record

    def revoke(self, raw_key: str) -> bool:
        record = self._keys.get(_hash(raw_key))
        if record is None:
            return False
        record.revoked = True
        return True
