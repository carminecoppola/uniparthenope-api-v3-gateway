"""Cache TTL con single-flight e stale-while-revalidate (fix PRB-06).

- Entro il TTL: hit senza ricaricare.
- Oltre il TTL con loader che fallisce: si serve il dato STALE dichiarandolo
  (flag), invece di far esplodere la rotta.
- Nessun dato stale disponibile: l'errore si propaga, visibile.

Fix audit pre-deploy: le chiavi includono la query string delle richieste
pubbliche (es. proxy upstream), quindi un chiamante esterno può generare
chiavi arbitrarie a piacere. Senza un tetto, `_entries`/`_locks` crescono
senza limite -> esaurimento memoria. `max_entries` applica un'evizione LRU.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, time_fn=time.time, max_entries: int = 2000) -> None:
        self._now = time_fn
        self._max_entries = max_entries
        self._entries: "OrderedDict[object, dict]" = OrderedDict()
        self._locks: "OrderedDict[object, threading.Lock]" = OrderedDict()
        self._locks_guard = threading.Lock()

    def _lock_for(self, key) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.pop(key, None)
            if lock is None:
                lock = threading.Lock()
                while len(self._locks) >= self._max_entries:
                    self._locks.popitem(last=False)
            self._locks[key] = lock   # più recente in coda
            return lock

    def _remember(self, key, entry: dict) -> None:
        self._entries.pop(key, None)
        self._entries[key] = entry
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)   # evizione LRU

    def get_or_load(self, key, loader, ttl: float, stale_ttl: float | None = None):
        """Ritorna (valore, stale: bool)."""
        entry = self._entries.get(key)
        if entry is not None and self._now() <= entry["fresh_until"]:
            self._entries.move_to_end(key)
            return entry["value"], False
        with self._lock_for(key):   # single-flight: un solo loader per chiave
            entry = self._entries.get(key)
            now = self._now()
            if entry is not None and now <= entry["fresh_until"]:
                self._entries.move_to_end(key)
                return entry["value"], False
            try:
                value = loader()
            except Exception:
                if entry is not None and now <= entry["stale_until"]:
                    return entry["value"], True   # stale dichiarato, non nascosto
                raise
            horizon = stale_ttl if stale_ttl is not None else ttl
            self._remember(key, {"value": value,
                                 "fresh_until": now + ttl,
                                 "stale_until": now + horizon})
            return value, False

    def invalidate(self, key) -> None:
        self._entries.pop(key, None)
