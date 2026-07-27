"""Test di sessioni, rate limit, cache SWR, circuit breaker, modello errori."""
import unittest

from app.core.cache import TTLCache
from app.core.circuit import CircuitBreaker
from app.core.errors import (ApiError, AuthRequired, PlanEntryNotFound,
                             RateLimited, SessionExpired)
from app.core.ratelimit import TokenBucket
from app.core.security import SessionStore


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.store = SessionStore(access_ttl_s=900, refresh_ttl_s=3600,
                                  time_fn=self.clock)
        self.tokens = self.store.create("student", [], 2001)

    def test_access_token_resolves(self):
        session = self.store.resolve_access(self.tokens["accessToken"])
        self.assertEqual(session.username, "student")

    def test_access_token_expires_at_15_minutes(self):
        self.clock.advance(901)
        with self.assertRaises(SessionExpired):
            self.store.resolve_access(self.tokens["accessToken"])

    def test_missing_token_401(self):
        with self.assertRaises(AuthRequired):
            self.store.resolve_access(None)

    def test_refresh_rotates(self):
        new = self.store.refresh(self.tokens["refreshToken"])
        self.assertNotEqual(new["accessToken"], self.tokens["accessToken"])
        self.store.resolve_access(new["accessToken"])  # valido

    def test_refresh_reuse_revokes_session(self):
        """Riuso di un refresh già ruotato = furto sospetto → revoca totale."""
        new = self.store.refresh(self.tokens["refreshToken"])
        with self.assertRaises(SessionExpired):
            self.store.refresh(self.tokens["refreshToken"])  # riuso
        with self.assertRaises(ApiError):
            self.store.resolve_access(new["accessToken"])  # tutto revocato

    def test_logout_revokes(self):
        self.store.logout_by_access(self.tokens["accessToken"])
        with self.assertRaises(ApiError):
            self.store.resolve_access(self.tokens["accessToken"])


class RateLimitTests(unittest.TestCase):
    def test_five_per_minute_then_429_material(self):
        clock = FakeClock()
        bucket = TokenBucket(capacity=5, time_fn=clock)
        for _ in range(5):
            allowed, _ = bucket.allow("user|ip")
            self.assertTrue(allowed)
        allowed, retry = bucket.allow("user|ip")
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)
        clock.advance(13)  # ~12s per un token a 5/min
        allowed, _ = bucket.allow("user|ip")
        self.assertTrue(allowed)

    def test_keys_are_independent(self):
        bucket = TokenBucket(capacity=1)
        self.assertTrue(bucket.allow("a")[0])
        self.assertTrue(bucket.allow("b")[0])


class CacheTests(unittest.TestCase):
    def test_fresh_hit_does_not_reload(self):
        clock = FakeClock()
        cache = TTLCache(time_fn=clock)
        calls = []
        loader = lambda: calls.append(1) or "v"
        cache.get_or_load("k", loader, ttl=60)
        value, stale = cache.get_or_load("k", loader, ttl=60)
        self.assertEqual(value, "v")
        self.assertFalse(stale)
        self.assertEqual(len(calls), 1)

    def test_stale_served_on_loader_failure(self):
        """Guasto upstream oltre il TTL → dato stale con flag, non crash."""
        clock = FakeClock()
        cache = TTLCache(time_fn=clock)
        cache.get_or_load("k", lambda: "v1", ttl=60, stale_ttl=3600)
        clock.advance(61)

        def failing():
            raise RuntimeError("upstream giu")

        value, stale = cache.get_or_load("k", failing, ttl=60, stale_ttl=3600)
        self.assertEqual(value, "v1")
        self.assertTrue(stale)

    def test_failure_without_stale_propagates(self):
        cache = TTLCache()
        with self.assertRaises(RuntimeError):
            cache.get_or_load("nuova", self._boom, ttl=60)

    @staticmethod
    def _boom():
        raise RuntimeError("no dato, no stale: errore visibile")


class CircuitTests(unittest.TestCase):
    def test_opens_after_five_failures_and_recovers(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=5, reset_timeout_s=30,
                                 time_fn=clock)
        for _ in range(5):
            self.assertTrue(breaker.allow())
            breaker.record_failure()
        self.assertFalse(breaker.allow())      # aperto
        clock.advance(31)
        self.assertTrue(breaker.allow())        # half-open
        breaker.record_success()
        self.assertEqual(breaker.state, "closed")

    def test_half_open_failure_reopens(self):
        clock = FakeClock()
        breaker = CircuitBreaker(failure_threshold=1, reset_timeout_s=30,
                                 time_fn=clock)
        breaker.record_failure()
        self.assertFalse(breaker.allow())
        clock.advance(31)
        self.assertTrue(breaker.allow())
        breaker.record_failure()
        self.assertFalse(breaker.allow())


class ErrorModelTests(unittest.TestCase):
    def test_problem_shape_rfc9457(self):
        problem = PlanEntryNotFound("detail x").problem("req_1")
        self.assertEqual(problem["status"], 422)
        self.assertEqual(problem["code"], "plan_entry_not_found")
        self.assertEqual(problem["requestId"], "req_1")
        self.assertTrue(problem["type"].endswith("plan_entry_not_found"))

    def test_rate_limited_carries_retry_after(self):
        err = RateLimited(12)
        self.assertEqual(err.retry_after, 12)
        self.assertEqual(err.problem()["retryAfter"], 12)


if __name__ == "__main__":
    unittest.main()
