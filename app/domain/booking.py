"""Logica di prenotazione. Qui vive la correzione di PRB-12 (`adsceId: None`).

Regola non negoziabile: un identificatore assente è un errore di dominio
(422 `plan_entry_not_found`), non un valore. Nessun None può raggiungere
l'upstream, dove produrrebbe un 500 indistinguibile da un guasto reale.
"""
from __future__ import annotations

import logging

from ..adapters.esse3.mappers import apply_exam_outcome
from ..core.cache import TTLCache
from ..core.errors import PlanEntryNotFound, ValidationFailed

logger = logging.getLogger("v3.booking")


class BookingService:
    def __init__(self, adapter, plan_cache: TTLCache | None = None,
                 plan_ttl_s: int = 900, outcome_ttl_s: int = 900,
                 outcome_passed_ttl_s: int = 86_400,
                 outcome_workers: int = 8) -> None:
        self._adapter = adapter
        self._cache = plan_cache if plan_cache is not None else TTLCache()
        self._plan_ttl = plan_ttl_s
        self._outcome_ttl = outcome_ttl_s
        self._outcome_passed_ttl = outcome_passed_ttl_s
        self._outcome_workers = outcome_workers

    # -- piano di studi ----------------------------------------------------
    def plan(self, career_id: int):
        entries, _stale = self._cache.get_or_load(
            ("plan", career_id),
            lambda: self._load_plan(career_id),
            ttl=self._plan_ttl,
            stale_ttl=self._plan_ttl * 4,
        )
        return entries

    def _load_plan(self, career_id: int):
        entries, skipped = self._adapter.get_plan(career_id)
        if skipped:
            # Le righe malformate vengono scartate E SEGNALATE: mai in silenzio.
            logger.warning("Libretto: %s righe scartate perché malformate (careerId=%s)",
                           skipped, career_id)
        return entries

    # -- correzione PRB-12 ---------------------------------------------------
    def resolve_adsce_id(self, career_id: int, ad_id: int,
                         aa_off_id: int | None = None) -> int:
        """Risolve adsceId dal libretto della carriera attiva.

        Se non lo trova, SOLLEVA. Non ritorna mai None e non inoltra mai
        None a monte.
        """
        if ad_id is None:
            raise ValidationFailed("adId mancante nella richiesta.")
        entries = self.plan(career_id)
        candidates = [e for e in entries if e.ad_id == ad_id]
        if aa_off_id is not None:
            narrowed = [e for e in candidates if e.aa_off_id in (None, aa_off_id)]
            if narrowed:
                candidates = narrowed
        if not candidates:
            # Log diagnostico senza dati personali: solo identificatori tecnici.
            logger.warning("adsceId non risolto (adId=%s aaOffId=%s planSize=%s careerId=%s)",
                           ad_id, aa_off_id, len(entries), career_id)
            raise PlanEntryNotFound(
                "L'insegnamento non risulta nel piano di studi della carriera attiva.")
        adsce_id = candidates[0].adsce_id
        if not isinstance(adsce_id, int):  # difesa in profondità
            raise PlanEntryNotFound("adsceId non valido nel libretto.")
        return adsce_id

    # -- esiti del libretto ----------------------------------------------------
    def _outcome_key(self, career_id: int, adsce_id: int):
        return ("planOutcome", career_id, adsce_id)

    def complete_outcomes(self, career, entries, workers: int | None = None):
        """Completa gli esiti mancanti, chiedendoli tutti insieme.

        Ritorna (righe_complete, letture, errori). `letture` spiega da dove
        arriva ogni riga (già nel libretto / dalla cache / lette adesso):
        sono i numeri che spiegano il tempo di risposta, utili in
        diagnostica quando la schermata è più lenta del previsto.
        """
        already_known = []
        to_complete = []
        for entry in entries:
            if entry.outcome_known:
                already_known.append(entry)
            else:
                to_complete.append(entry)

        from_cache = 0
        to_read = []
        result = {e.adsce_id: e for e in already_known}

        for entry in to_complete:
            cached = self._cache.get(self._outcome_key(career.career_id, entry.adsce_id))
            if cached is not None:
                result[entry.adsce_id] = apply_exam_outcome(entry, cached)
                from_cache += 1
            else:
                to_read.append(entry)
                result[entry.adsce_id] = entry

        errors: dict[int, dict] = {}
        if to_read:
            outcomes, errors = self._adapter.get_exam_outcomes_batch(
                career, [e.adsce_id for e in to_read], workers or self._outcome_workers)
            for entry in to_read:
                outcome = outcomes.get(entry.adsce_id)
                if outcome is None:
                    continue
                completed = apply_exam_outcome(entry, outcome)
                result[entry.adsce_id] = completed
                # Un esame superato non cambia più: resta in cache a lungo.
                self._cache.set(
                    self._outcome_key(career.career_id, entry.adsce_id), outcome,
                    ttl=(self._outcome_passed_ttl if completed.passed
                        else self._outcome_ttl))

        stats = {"giaNelLibretto": len(already_known), "daMemoria": from_cache,
                 "letteAdesso": len(to_read)}
        ordered = [result[e.adsce_id] for e in entries]
        return ordered, stats, errors

    def plan_with_outcomes(self, career, workers: int | None = None):
        """Elenco del piano con gli esiti completati (stato/voto/crediti)."""
        entries = self.plan(career.career_id)
        return self.complete_outcomes(career, entries, workers=workers)

    def plan_summary(self, career, workers: int | None = None) -> dict:
        """Solo i totali: crediti acquisiti, esami superati, medie.

        Calcolati sulle righe già completate: non aggiunge nessuna attesa
        rispetto all'elenco.
        """
        entries, _stats, errors = self.plan_with_outcomes(career, workers=workers)
        summary = _summary(entries)
        if errors:
            summary["errors"] = {str(k): v for k, v in errors.items()}
        return summary

    def entry_detail(self, career, adsce_id: int, workers: int | None = None):
        """Una sola riga del libretto, completa di esito, o None se assente."""
        entries = self.plan(career.career_id)
        entry = next((e for e in entries if e.adsce_id == adsce_id), None)
        if entry is None:
            return None
        completed, _stats, errors = self.complete_outcomes(career, [entry],
                                                           workers=workers)
        return completed[0], errors

    def refresh_entry(self, career, adsce_id: int):
        """Dimentica solo l'esito di un insegnamento e lo rilegge.

        Svuotare l'intero libretto renderebbe di nuovo lenta la schermata
        senza motivo: qui si invalida solo la chiave di quell'insegnamento.
        """
        self._cache.invalidate(self._outcome_key(career.career_id, adsce_id))
        return self.entry_detail(career, adsce_id)

    # -- appelli ---------------------------------------------------------------
    def exam_sessions(self, career, ad_id: int | None = None):
        sessions, skipped = self._adapter.get_exam_sessions(career, ad_id=ad_id)
        if skipped:
            logger.warning("Appelli: %s righe scartate perché malformate", skipped)
        return sessions

    def exam_sessions_batch(self, career, ad_ids: list[int], workers: int | None = None):
        """Più insegnamenti in una sola chiamata (in parallelo lato server).

        Ritorna (sessioni, errori_per_ad): un adId fallito non fa fallire
        gli altri, finisce nel dizionario errori invece che nella lista.
        """
        sessions, skipped, errori = self._adapter.get_exam_sessions_batch(
            career, ad_ids, workers=workers)
        if skipped:
            logger.warning("Appelli batch: %s righe scartate perché malformate", skipped)
        if errori:
            logger.warning("Appelli batch: %s adId falliti su %s richiesti",
                           len(errori), len(ad_ids))
        return sessions, errori

    # -- prenotazione (fix PRB-12) ----------------------------------------------
    def book(self, career, app_id: int, ad_id: int, aa_off_id: int | None = None,
             dry_run: bool = False) -> dict:
        adsce_id = self.resolve_adsce_id(career.career_id, ad_id, aa_off_id)
        # Da qui in poi adsce_id è garantito int: nessun None può passare.
        if dry_run:
            return {"dryRun": True, "wouldBook": {
                "appId": app_id, "adId": ad_id, "adsceId": adsce_id,
                "careerId": career.career_id}}
        result = self._adapter.book_exam(career=career, app_id=app_id,
                                         ad_id=ad_id, adsce_id=adsce_id)
        self._cache.invalidate(("plan", career.career_id))
        return {"dryRun": False, "reservation": result}

    # -- cancellazione (PRB-14: idempotente + dryRun) ------------------------------
    def cancel(self, career, reservation_id: str, dry_run: bool = False) -> dict:
        if dry_run:
            reservations, _ = self._adapter.get_reservations(career)
            exists = any(r.reservation_id == str(reservation_id) for r in reservations)
            return {"dryRun": True, "exists": exists,
                    "wouldDelete": exists, "alreadyGone": not exists}
        deleted = self._adapter.delete_reservation(career, str(reservation_id))
        # Idempotente: cancellare due volte non è un errore.
        return {"dryRun": False, "deleted": bool(deleted), "alreadyGone": not deleted}


def filter_entries(entries, anno: int | None = None, semestre: str | None = None,
                   stato: str | None = None):
    """Riduce l'elenco per anno di corso, semestre e stato dell'esito.

    I filtri si sommano. `stato` accetta 'superato', 'frequentato' o
    'pianificato' (gli stessi valori esposti in PlanEntry.stato_des).
    """
    result = list(entries)
    if anno is not None:
        result = [e for e in result if e.anno == anno]
    if semestre:
        wanted = semestre.strip().lower()
        result = [e for e in result if wanted in e.semestre.lower()]
    if stato:
        wanted = stato.strip().lower()
        if wanted == "superato":
            result = [e for e in result if e.passed]
        else:
            result = [e for e in result
                     if not e.passed and e.stato_des.lower() == wanted]
    return result


def _summary(entries) -> dict:
    """Crediti, esami superati e medie calcolati sulle righe già disponibili.

    I voti non numerici (idoneità) contano per i crediti ma non per la
    media: non esiste un "18/30" da mediare per un'idoneità.
    """
    passed = [e for e in entries if e.passed]
    cfu_total = sum(e.cfu or 0 for e in entries)
    cfu_earned = sum(e.cfu or 0 for e in passed)

    grades = []
    for entry in passed:
        try:
            value = float(str(entry.grade).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if 18 <= value <= 31:
            grades.append((min(value, 30.0), entry.cfu or 0))

    arithmetic_mean = round(sum(v for v, _ in grades) / len(grades), 2) if grades else None
    weight = sum(c for _, c in grades)
    weighted_mean = (round(sum(v * c for v, c in grades) / weight, 2)
                    if weight else arithmetic_mean)

    return {
        "insegnamenti": len(entries),
        "superati": len(passed),
        "daSostenere": len(entries) - len(passed),
        "cfuTotali": round(cfu_total, 1),
        "cfuAcquisiti": round(cfu_earned, 1),
        "votiConsiderati": len(grades),
        "mediaAritmetica": arithmetic_mean,
        "mediaPonderata": weighted_mean,
    }
