"""Configurazione da variabili d'ambiente. Nessun segreto nel codice.

Regola: i percorsi upstream NON confermati dalla spec restano vuoti di
default; le rotte corrispondenti rispondono 503 `upstream_path_not_configured`
invece di inventare percorsi (niente TODO silenziosi).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _route_flags() -> dict[str, str]:
    """ROUTE_FLAGS="exams=v3,bus=proxy" — interruttore per rotta (cancello di parità)."""
    flags: dict[str, str] = {}
    for piece in os.environ.get("ROUTE_FLAGS", "").split(","):
        if "=" in piece:
            key, _, value = piece.partition("=")
            flags[key.strip()] = value.strip()
    return flags


@dataclass(frozen=True)
class Settings:
    # Modalità: True = adapter ESSE3 simulato (funziona offline, password 'demo')
    mock_esse3: bool = True
    # Upstream reale v1/v2
    upstream_base: str = "https://api.uniparthenope.it"
    upstream_timeout_s: float = 25.0
    # Percorsi non ancora confermati dalla spec: vuoti → 503 tipizzato
    upstream_photo_path: str = ""
    upstream_bus_path: str = ""
    upstream_dining_path: str = ""
    # Sessioni
    access_ttl_s: int = 900          # 15 minuti
    refresh_ttl_s: int = 2_592_000   # 30 giorni, rotante
    login_rate_per_min: int = 5
    # Cache (secondi)
    events_ttl_s: int = 21_600
    bus_ttl_s: int = 3_600
    dining_ttl_s: int = 3_600
    plan_ttl_s: int = 900
    # Interruttore v3/proxy per rotta
    route_flags: dict = field(default_factory=dict)


def load_settings() -> Settings:
    return Settings(
        mock_esse3=_bool_env("MOCK_ESSE3", True),
        upstream_base=os.environ.get("UPSTREAM_BASE", "https://api.uniparthenope.it"),
        upstream_timeout_s=_float_env("UPSTREAM_TIMEOUT_S", 25.0),
        upstream_photo_path=os.environ.get("UPSTREAM_PHOTO_PATH", ""),
        upstream_bus_path=os.environ.get("UPSTREAM_BUS_PATH", ""),
        upstream_dining_path=os.environ.get("UPSTREAM_DINING_PATH", ""),
        access_ttl_s=_int_env("ACCESS_TTL_S", 900),
        refresh_ttl_s=_int_env("REFRESH_TTL_S", 2_592_000),
        login_rate_per_min=_int_env("LOGIN_RATE_PER_MIN", 5),
        events_ttl_s=_int_env("EVENTS_TTL_S", 21_600),
        bus_ttl_s=_int_env("BUS_TTL_S", 3_600),
        dining_ttl_s=_int_env("DINING_TTL_S", 3_600),
        plan_ttl_s=_int_env("PLAN_TTL_S", 900),
        route_flags=_route_flags(),
    )


settings = load_settings()
