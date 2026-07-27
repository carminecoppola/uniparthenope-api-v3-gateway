"""Circuit breaker: 5 fallimenti → aperto 30 s → half-open → chiuso/riaperto.

Evita di martellare un upstream già in difficoltà e trasforma i guasti in
503 `upstream_unavailable` immediati e tipizzati.
"""
from __future__ import annotations

import time

from .errors import UpstreamUnavailable


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout_s: float = 30.0,
                 time_fn=time.time) -> None:
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout_s
        self._now = time_fn
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half-open" if self._half_open else "open"

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if self._now() - self._opened_at >= self._reset_timeout:
            self._half_open = True   # una richiesta di prova
            return True
        return False

    def record_failure(self) -> None:
        if self._half_open:
            # La prova è fallita: si riapre da capo.
            self._opened_at = self._now()
            self._half_open = False
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._now()
            self._half_open = False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open = False

    def guard(self) -> None:
        """Da chiamare prima di ogni richiesta upstream."""
        if not self.allow():
            raise UpstreamUnavailable(
                "Circuito aperto verso l'upstream: richieste sospese temporaneamente.")
