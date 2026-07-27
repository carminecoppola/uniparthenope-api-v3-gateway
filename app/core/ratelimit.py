"""Token bucket per chiave (username|IP) — fix PRB-07.

Default: 5 tentativi/minuto sul login. Il sesto riceve 429 con Retry-After
materiale, non un errore generico.
"""
from __future__ import annotations

import math
import time


class TokenBucket:
    def __init__(self, capacity: int, per_seconds: float = 60.0,
                 time_fn=time.time) -> None:
        self._capacity = float(capacity)
        self._rate = float(capacity) / per_seconds   # token al secondo
        self._now = time_fn
        self._buckets: dict = {}   # key -> {"tokens": float, "updated": float}

    def allow(self, key) -> tuple[bool, int]:
        """Ritorna (permesso, retry_after_secondi)."""
        now = self._now()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = {"tokens": self._capacity, "updated": now}
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket["updated"])
            bucket["tokens"] = min(self._capacity,
                                   bucket["tokens"] + elapsed * self._rate)
            bucket["updated"] = now
        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True, 0
        missing = 1.0 - bucket["tokens"]
        return False, max(1, math.ceil(missing / self._rate))
