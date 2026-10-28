import tracemalloc
import uuid

import pytest

from app.schemas.common import AuthContext
from app.services.quota_service import period_start, seconds_to_reset
from app.services.ratelimit_service import InMemoryRateLimiter, RateLimitService
from app.utils.errors import RateLimited


def _auth(rpm=5, tpm=1000, key=None) -> AuthContext:
    return AuthContext(
        key_id=key or uuid.uuid4(),
        key_prefix="lgw_x",
        role="client",
        scopes=frozenset(),
        project_id=uuid.uuid4(),
        project_slug="p",
        log_payloads=False,
        payload_retention_days=7,
        rpm_limit=rpm,
        tpm_limit=tpm,
    )


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_rpm_sixth_request_rejected_with_retry_after():  # AC1
    clock = Clock()
    svc = RateLimitService(clock=clock)
    auth = _auth(rpm=5)
    for i in range(5):
        _, headers = svc.check(auth, 10)
        assert headers["X-RateLimit-Remaining-Requests"] == str(4 - i)  # AC4
        clock.t += 2  # request di detik 0, 2, 4, 6, 8
    with pytest.raises(RateLimited) as info:
        svc.check(auth, 10)
    # request tertua (detik 0) keluar jendela pada detik 60 → sekarang detik 10 → 50 s
    assert info.value.headers["Retry-After"] == "50"
    assert info.value.headers["X-RateLimit-Remaining-Requests"] == "0"
    assert info.value.http_status == 429
    clock.t += 50
    svc.check(auth, 10)  # jendela bergeser → diizinkan lagi


def test_tpm_correction_refunds_unused_tokens():  # AC2
    clock = Clock()
    svc = RateLimitService(clock=clock)
    auth = _auth(rpm=100, tpm=1000)
    res, headers = svc.check(auth, 900)  # estimasi besar (input + max_tokens)
    assert headers["X-RateLimit-Remaining-Tokens"] == "100"
    with pytest.raises(RateLimited, match="token"):
        svc.check(auth, 500)
    svc.settle(res, actual_tokens=50)  # pemakaian aktual kecil → 850 kembali
    _, headers = svc.check(auth, 500)
    assert headers["X-RateLimit-Remaining-Tokens"] == "450"
    svc.settle(res, actual_tokens=0)  # settle kedua diabaikan


def test_tpm_actual_above_estimate_adds_debt_and_refills():
    clock = Clock()
    svc = RateLimitService(clock=clock)
    auth = _auth(rpm=100, tpm=600)  # isi ulang 10 token/detik
    res, _ = svc.check(auth, 100)
    svc.settle(res, actual_tokens=700)  # 500 → -100 (utang)
    with pytest.raises(RateLimited) as info:
        svc.check(auth, 50)
    assert info.value.headers["Retry-After"] == "15"  # (50 - (-100)) / 10
    clock.t += 15
    svc.check(auth, 50)


def test_release_returns_slot_and_tokens():
    svc = RateLimitService(clock=Clock())
    auth = _auth(rpm=1, tpm=100)
    res, _ = svc.check(auth, 80)
    svc.release(res)  # mis. kuota ditolak setelah rate limit lolos
    svc.check(auth, 80)


def test_memory_stable_after_cleanup_10000_keys():  # AC5
    clock = Clock()
    backend = InMemoryRateLimiter()
    svc = RateLimitService(backend, clock=clock)
    tracemalloc.start()
    for _ in range(10_000):
        svc.check(_auth(), 10)
    assert backend.size() == 10_000
    peak_full = tracemalloc.get_traced_memory()[0]
    clock.t += 601
    assert svc.cleanup() == 10_000 and backend.size() == 0
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    assert after < peak_full / 4


def test_quota_period_math():
    from datetime import UTC, datetime

    now = datetime(2026, 10, 28, 23, 0, 0, tzinfo=UTC)
    assert seconds_to_reset("daily", now) == 3600
    assert seconds_to_reset("monthly", now) == (3 * 24 + 1) * 3600
    assert str(period_start("monthly", now)) == "2026-10-01"
    dec = datetime(2026, 12, 31, 12, 0, tzinfo=UTC)
    assert seconds_to_reset("monthly", dec) == 12 * 3600  # → 1 Jan 2027
