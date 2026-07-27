"""Mapper upstream → dominio.

Regole:
- nessuna chiave viene "indovinata": si accettano solo le varianti note,
  tutte esplicite qui sotto;
- le righe malformate vengono scartate E CONTATE, mai ignorate in silenzio
  (anti PRB-01);
- le date escono sempre in ISO-8601 (YYYY-MM-DD).
"""
from __future__ import annotations

import re

from ...domain.models import ExamSession, PlanEntry, Reservation

# Stati appello che consentono la prenotazione. Corregge il difetto
# osservato in v1/v2 (deny-list `bad_status=["C"]`): la regola giusta
# è una ALLOW-list.
BOOKABLE_STATUSES = {"P", "I"}

_DATE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DATE_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")


def normalize_date(value) -> str:
    if not value:
        return ""
    text = str(value).strip()
    m = _DATE_ISO.match(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_DMY.match(text)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def _first(entry: dict, *keys, default=None):
    for key in keys:
        if key in entry and entry[key] is not None:
            return entry[key]
    return default


def _int_or_none(value):
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def map_plan(raw, career_id=None):
    """Ritorna (righe_valide, scartate).

    Accetta sia una lista sia il wrapper {"dettaglioTratto": [...]}.
    Una riga senza adsceId o adId è malformata: scartata e contata.
    """
    if isinstance(raw, dict):
        raw = _first(raw, "dettaglioTratto", "plan", "righe", default=[])
    entries, skipped = [], 0
    for item in raw or []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        adsce = _int_or_none(_first(item, "adsceId", "adsce_id", "ADSCE_ID"))
        ad = _int_or_none(_first(item, "adId", "ad_id", "AD_ID"))
        if adsce is None or ad is None:
            skipped += 1
            continue
        entries.append(PlanEntry(
            adsce_id=adsce,
            ad_id=ad,
            ad_des=str(_first(item, "adDes", "ad_des", "des", default="")),
            aa_off_id=_int_or_none(_first(item, "aaOffId", "aa_off_id")),
            career_id=career_id,
        ))
    return entries, skipped


def map_exam_sessions(raw):
    if isinstance(raw, dict):
        raw = _first(raw, "appelli", "data", "items", default=[])
    sessions, skipped = [], 0
    for item in raw or []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        app_id = _int_or_none(_first(item, "appId", "app_id"))
        ad_id = _int_or_none(_first(item, "adId", "ad_id"))
        if app_id is None or ad_id is None:
            skipped += 1
            continue
        status = str(_first(item, "stato", "status", "statoAperturaApp",
                            default="")).strip().upper()
        bookable = status in BOOKABLE_STATUSES
        sessions.append(ExamSession(
            app_id=app_id,
            ad_id=ad_id,
            ad_des=str(_first(item, "adDes", "desApp", "des", default="")),
            aa_off_id=_int_or_none(_first(item, "aaOffId", "aa_off_id")),
            date=normalize_date(_first(item, "dataInizioApp", "dataApp", "data", "date")),
            status=status,
            bookable=bookable,
            reason="" if bookable else
                   f"Stato appello '{status or 'sconosciuto'}' non prenotabile",
        ))
    return sessions, skipped


def map_reservations(raw):
    if isinstance(raw, dict):
        raw = _first(raw, "prenotazioni", "data", "items", default=[])
    out, skipped = [], 0
    for item in raw or []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        rid = _first(item, "reservationId", "prenotazioneId", "id")
        app_id = _int_or_none(_first(item, "appId", "app_id"))
        ad_id = _int_or_none(_first(item, "adId", "ad_id"))
        adsce = _int_or_none(_first(item, "adsceId", "adsce_id"))
        if rid is None or app_id is None or ad_id is None or adsce is None:
            skipped += 1
            continue
        out.append(Reservation(
            reservation_id=str(rid),
            app_id=app_id,
            ad_id=ad_id,
            adsce_id=adsce,
            ad_des=str(_first(item, "adDes", "des", default="")),
            date=normalize_date(_first(item, "dataApp", "data", "date")),
        ))
    return out, skipped
