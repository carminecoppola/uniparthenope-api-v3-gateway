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
    # Appelli: chiamata DIRETTA a esse3.cineca.it (bypassa il backend legacy,
    # che espone solo la prima pagina). Confermato raggiungibile dal server
    # del gateway il 28/07/2026 (401 atteso, nessun blocco di rete).
    esse3_direct_base: str = "https://uniparthenope.esse3.cineca.it/e3rest/api"
    esse3_direct_timeout_s: float = 20.0
    # Appelli-docente (creazione/modifica): l'e3rest sopra è sola lettura,
    # quindi qui si passa dall'area WEB di ESSE3 (stesse credenziali, cookie
    # JSESSIONID). Vuoto di default: finché non è confermato/configurato le
    # rotte /professors/me/exam-sessions rispondono 503, mai un percorso
    # inventato (stessa regola di upstream_photo_path ecc.).
    esse3_web_base: str = ""
    esse3_web_timeout_s: float = 25.0
    # True finché non abbiamo un HAR di salvataggio riuscito: valida e
    # prepara il payload ma non lo invia a ESSE3 (niente scritture accidentali
    # su dati d'esame reali durante l'integrazione).
    esse3_web_dry_run_writes: bool = True
    # esse3 rifiuta con 412 un limit > 100 (verificato il 28/07/2026 con
    # credenziali reali: "valore parametro limit errato: inserire un
    # valore minore o uguale a 100").
    appelli_page_size: int = 100
    appelli_max_pages: int = 25       # tetto di sicurezza: 5000 appelli per AD bastano
    appelli_workers: int = 5          # AD in parallelo di default nella /exam-sessions batch
    appelli_max_workers: int = 20     # limite duro, per non martellare esse3
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
        esse3_direct_base=os.environ.get(
            "ESSE3_DIRECT_BASE", "https://uniparthenope.esse3.cineca.it/e3rest/api"),
        esse3_direct_timeout_s=_float_env("ESSE3_DIRECT_TIMEOUT_S", 20.0),
        esse3_web_base=os.environ.get("ESSE3_WEB_BASE", ""),
        esse3_web_timeout_s=_float_env("ESSE3_WEB_TIMEOUT_S", 25.0),
        esse3_web_dry_run_writes=_bool_env("ESSE3_WEB_DRY_RUN_WRITES", True),
        appelli_page_size=_int_env("APPELLI_PAGE_SIZE", 200),
        appelli_max_pages=_int_env("APPELLI_MAX_PAGES", 25),
        appelli_workers=_int_env("APPELLI_WORKERS", 5),
        appelli_max_workers=_int_env("APPELLI_MAX_WORKERS", 20),
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
