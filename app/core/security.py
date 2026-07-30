"""Sessioni con token opachi (fix PRB-03).

- Access token: 15 minuti. Refresh token: 30 giorni, ROTANTE.
- I token sono conservati solo come SHA-256: un dump della memoria del
  server non rivela token spendibili.
- Riuso di un refresh già ruotato = sospetto furto → revoca dell'intera sessione.
- Le credenziali upstream restano nella memoria del processo, mai sul device.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field

from .errors import AuthRequired, SessionExpired


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Session:
    session_id: str
    username: str
    careers: list
    # None per gli account senza carriera studente (docenti puri): le rotte
    # studente useranno _career() e falliranno con un errore di dominio
    # chiaro invece di un IndexError in fase di creazione della sessione.
    career_id: int | None
    data: dict = field(default_factory=dict)
    revoked: bool = False


class SessionStore:
    def __init__(self, access_ttl_s: int = 900, refresh_ttl_s: int = 2_592_000,
                 time_fn=time.time) -> None:
        self._now = time_fn
        self._access_ttl = access_ttl_s
        self._refresh_ttl = refresh_ttl_s
        self._access: dict[str, dict] = {}    # sha256 -> {sid, exp}
        self._refresh: dict[str, dict] = {}   # sha256 -> {sid, exp, used}
        self._sessions: dict[str, Session] = {}

    # -- emissione -----------------------------------------------------
    def _issue(self, sid: str) -> dict:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(48)
        now = self._now()
        self._access[_hash(access)] = {"sid": sid, "exp": now + self._access_ttl}
        self._refresh[_hash(refresh)] = {"sid": sid, "exp": now + self._refresh_ttl,
                                         "used": False}
        return {"tokenType": "Bearer", "accessToken": access,
                "refreshToken": refresh, "expiresIn": self._access_ttl}

    def create(self, username: str, careers: list, career_id: int | None,
               data: dict | None = None) -> dict:
        sid = secrets.token_urlsafe(16)
        self._sessions[sid] = Session(sid, username, list(careers), career_id,
                                      dict(data or {}))
        return self._issue(sid)

    # -- risoluzione ------------------------------------------------------
    def resolve_access(self, token: str | None) -> Session:
        if not token:
            raise AuthRequired("Header Authorization: Bearer <accessToken> richiesto.")
        record = self._access.get(_hash(token))
        if record is None:
            raise AuthRequired("Token di accesso non riconosciuto o revocato.")
        if self._now() > record["exp"]:
            raise SessionExpired("Access token scaduto: usare il refresh token.")
        session = self._sessions.get(record["sid"])
        if session is None or session.revoked:
            raise SessionExpired("Sessione revocata.")
        return session

    # -- refresh rotante ----------------------------------------------------
    def refresh(self, refresh_token: str | None) -> dict:
        record = self._refresh.get(_hash(refresh_token or ""))
        if record is None:
            raise SessionExpired("Refresh token non riconosciuto.")
        if record["used"]:
            # Riuso di un token già ruotato: possibile furto → revoca totale.
            self._revoke(record["sid"])
            raise SessionExpired("Refresh token riusato: sessione revocata per sicurezza.")
        if self._now() > record["exp"]:
            raise SessionExpired("Refresh token scaduto: nuovo login necessario.")
        record["used"] = True
        return self._issue(record["sid"])

    # -- revoca --------------------------------------------------------------
    def _revoke(self, sid: str) -> None:
        session = self._sessions.get(sid)
        if session is not None:
            session.revoked = True
            session.data.clear()   # rilascia anche l'adapter con le credenziali
        for store in (self._access, self._refresh):
            for h in [h for h, r in store.items() if r["sid"] == sid]:
                del store[h]

    def logout_by_access(self, token: str | None) -> None:
        record = self._access.get(_hash(token or ""))
        if record is not None:
            self._revoke(record["sid"])
