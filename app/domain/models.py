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
    date: str = ""            # ISO-8601 (YYYY-MM-DD), data dell'esame
    status: str = ""          # stato upstream grezzo
    bookable: bool = False    # regola risolta LATO SERVER, non nella UI
    reason: str = ""          # perché non prenotabile, quando bookable=False
    # Campi mostrati dai client legacy (v1 formatta_appello): il mapper li
    # scartava, ma sono già nel payload grezzo esse3 — nessuna chiamata in
    # più per recuperarli, solo esposti correttamente.
    teacher: str = ""              # cognome docente presidente commissione
    teacher_full: str = ""         # nome e cognome completi
    enrolled_count: int | None = None  # numIscritti
    note: str = ""
    description: str = ""          # desApp
    registration_start: str = ""   # ISO-8601, inizio finestra iscrizione
    registration_end: str = ""     # ISO-8601, fine finestra iscrizione


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    app_id: int
    ad_id: int
    adsce_id: int
    ad_des: str = ""
    date: str = ""
