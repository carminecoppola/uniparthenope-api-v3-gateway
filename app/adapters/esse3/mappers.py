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

# Stato dell'esito di un insegnamento nel libretto. Un codice non elencato
# qui NON viene tradotto a caso: resta il codice originale e va segnalato
# a parte (vedi map_plan/map_exam_outcome), mai mascherato in silenzio.
LIBRETTO_STATUS = {
    "S": ("Superato", True), "SUP": ("Superato", True),
    "SUPERATO": ("Superato", True), "SUPERATA": ("Superato", True),
    "V": ("Superato", True), "VER": ("Superato", True),
    "VERBALIZZATO": ("Superato", True),
    "F": ("Frequentato", False), "FRE": ("Frequentato", False),
    "FREQ": ("Frequentato", False), "FREQUENTATO": ("Frequentato", False),
    "FREQUENTATA": ("Frequentato", False),
    "P": ("Pianificato", False), "PIA": ("Pianificato", False),
    "PIAN": ("Pianificato", False), "PIANIFICATO": ("Pianificato", False),
    "PIANIFICATA": ("Pianificato", False),
}


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


def _float_or_none(value):
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in ("1", "S", "SI", "Y", "YES", "TRUE", "X")


def _grade_text(value) -> str:
    """Il voto come testo, senza decimali inutili (24.0 -> '24').

    Un'idoneità non è un numero: resta la parola così com'è.
    """
    if value in (None, ""):
        return ""
    number = _float_or_none(value)
    if number is None:
        return str(value).strip()
    if number == int(number):
        return str(int(number))
    return str(number)


def read_libretto_status(entry: dict):
    """Ricava (codice, descrizione, superato, riconosciuto) da una riga
    grezza di libretto o dalla risposta di checkExams. Se il codice non è
    fra quelli noti resta invariato e riconosciuto=False, così il
    chiamante può segnalarlo invece di mostrare un dato inventato.
    """
    raw = _first(entry, "statoDes", "stato", "adsceStatoCod", "statoCod",
                "esitoDes", "esito", default="")
    code = str(raw).strip().upper()
    if code in LIBRETTO_STATUS:
        des, passed = LIBRETTO_STATUS[code]
        return code, des, passed, True
    if not code:
        return "", "", False, True
    return code, code.capitalize(), False, False


def map_plan(raw, career_id=None):
    """Ritorna (righe_valide, scartate).

    Accetta sia una lista sia il wrapper {"dettaglioTratto": [...]}.
    Una riga senza adsceId o adId è malformata: scartata e contata.

    Se la riga del libretto contiene già stato/voto (capita non sempre:
    dipende da cosa restituisce esse3 per quella carriera), vengono presi
    da qui — zero chiamate aggiuntive per quell'insegnamento in
    get_exam_outcomes_batch.
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

        code, des, passed, _recognized = read_libretto_status(item)
        grade = _grade_text(_first(item, "esitoFinale", "voto", "votoEsame"))
        # Un voto registrato vale più del codice di stato: se c'è il voto,
        # l'esame è superato anche se il codice non lo dice esplicitamente.
        if grade and not passed:
            passed = True
            if not des:
                des = "Superato"
        outcome_known = bool(des) or bool(grade)

        entries.append(PlanEntry(
            adsce_id=adsce,
            ad_id=ad,
            # "nome" e' la chiave reale del libretto legacy (verificato il
            # 31/07/2026 con account studente reale: adDes/des non esistono
            # in questa risposta, sempre rimasti vuoti finora).
            ad_des=str(_first(item, "nome", "adDes", "ad_des", "des", default="")),
            aa_off_id=_int_or_none(_first(item, "aaOffId", "aa_off_id")),
            career_id=career_id,
            codice=str(_first(item, "codice", "adCod", default="")),
            cfu=_float_or_none(_first(item, "CFU", "peso", "cfu", "crediti")),
            anno=_int_or_none(_first(item, "annoId", "annoCorso", "anno", "aaOrdId")),
            semestre=str(_first(item, "semestre", "periodoDes", "partizione",
                                default="")),
            stato=code,
            stato_des=des,
            passed=passed,
            grade=grade,
            honors=_truthy(_first(item, "lodeFlg", "lode", default=False)),
            exam_date=normalize_date(_first(item, "dataEsame", "dataApp",
                                            "dataSuperamento", "data")),
            teacher=str(_first(item, "docente", "docenteDes", default="")),
            outcome_known=outcome_known,
        ))
    return entries, skipped


def map_exam_outcome(raw) -> dict | None:
    """Interpreta la risposta di checkExams per un singolo insegnamento.

    Ritorna un dizionario con le chiavi già lette (stato/voto/lode/data/
    docente) da fondere in una PlanEntry con apply_exam_outcome, oppure
    None se la risposta non dice nulla di utile: meglio un campo vuoto
    che un esito inventato.
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, dict):
        return None

    code, des, passed, _recognized = read_libretto_status(raw)
    grade = _grade_text(_first(raw, "esitoFinale", "voto", "votoEsame"))
    if grade and not passed:
        passed = True
        if not des:
            des = "Superato"
    if not des and not grade:
        return None

    return {
        "stato": code,
        "stato_des": des,
        "passed": passed,
        "grade": grade,
        "honors": _truthy(_first(raw, "lodeFlg", "lode", default=False)),
        "exam_date": normalize_date(_first(raw, "dataEsame", "dataApp",
                                           "dataSuperamento", "data")),
        "teacher": str(_first(raw, "docente", "docenteDes", default="")),
    }


def apply_exam_outcome(entry: PlanEntry, outcome: dict | None) -> PlanEntry:
    """Fonde l'esito letto a parte in una PlanEntry già esistente.

    Se l'esito è None la riga torna invariata: un insegnamento la cui
    lettura fallisce resta comunque nell'elenco, senza esito e senza dati
    inventati (l'errore va segnalato a parte dal chiamante).
    """
    from dataclasses import replace
    if outcome is None:
        return entry
    return replace(entry, outcome_known=True, **outcome)


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
        cognome = str(_first(item, "presidenteCognome", "docente", default="")).strip()
        nome = str(_first(item, "presidenteNome", default="")).strip()
        teacher = cognome.capitalize() if cognome else ""
        teacher_full = f"{teacher} {nome.capitalize()}".strip() if nome else teacher
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
            teacher=teacher,
            teacher_full=teacher_full,
            enrolled_count=_int_or_none(_first(item, "numIscritti", "enrolledCount")),
            note=str(_first(item, "note", default="")),
            description=str(_first(item, "desApp", "descrizione", default="")),
            registration_start=normalize_date(
                _first(item, "dataInizioIscr", "registrationStart")),
            registration_end=normalize_date(
                _first(item, "dataFineIscr", "registrationEnd")),
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
