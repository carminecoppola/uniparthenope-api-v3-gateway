"""Entità di dominio. Dataclass immutabili, nessuna dipendenza esterna."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Career:
    career_id: int
    mat_id: int | None = None
    stu_id: int | None = None
    cds_id: int | None = None
    cds_des: str = ""
    active: bool = True


@dataclass(frozen=True)
class PlanEntry:
    """Riga del libretto: l'UNICA fonte legittima di adsceId (fix PRB-12)."""
    adsce_id: int
    ad_id: int
    ad_des: str = ""
    aa_off_id: int | None = None
    career_id: int | None = None


@dataclass(frozen=True)
class ExamSession:
    app_id: int
    ad_id: int
    ad_des: str = ""
    aa_off_id: int | None = None
    date: str = ""            # ISO-8601 (YYYY-MM-DD)
    status: str = ""          # stato upstream grezzo
    bookable: bool = False    # regola risolta LATO SERVER, non nella UI
    reason: str = ""          # perché non prenotabile, quando bookable=False


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    app_id: int
    ad_id: int
    adsce_id: int
    ad_des: str = ""
    date: str = ""
