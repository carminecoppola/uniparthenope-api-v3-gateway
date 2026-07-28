"""Logica di prenotazione. Qui vive la correzione di PRB-12 (`adsceId: None`).

Regola non negoziabile: un identificatore assente è un errore di dominio
(422 `plan_entry_not_found`), non un valore. Nessun None può raggiungere
l'upstream, dove produrrebbe un 500 indistinguibile da un guasto reale.
"""
from __future__ import annotations

import logging

from ..core.cache import TTLCache
from ..core.errors import PlanEntryNotFound, ValidationFailed

logger = logging.getLogger("v3.booking")


class BookingService:
    def __init__(self, adapter, plan_cache: TTLCache | None = None,
                 plan_ttl_s: int = 900) -> None:
        self._adapter = adapter
        self._cache = plan_cache if plan_cache is not None else TTLCache()
        self._plan_ttl = plan_ttl_s

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
