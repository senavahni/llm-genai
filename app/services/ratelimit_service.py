"""Rate limit per API key tanpa Redis (TASK-16).

- RPM: sliding window log (deque timestamp) per key.
- TPM: token bucket per key (kapasitas = tpm_limit, isi ulang tpm_limit/60 per detik). Konsumsi
  awal = estimasi; setelah respons dikoreksi dengan usage aktual (refund / tambah utang).
Semua operasi sinkron tanpa `await` → atomik dalam satu event loop. State per proses: gateway
wajib 1 worker (PRD §17). Backend diabstraksikan (`RateLimiterBackend`) agar v2 bisa memakai
PostgreSQL."""

import collections
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.common import AuthContext
from app.utils.errors import RateLimited

WINDOW_S = 60.0
IDLE_CLEANUP_S = 600.0
DEFAULT_COMPLETION_ESTIMATE = 512


@dataclass
class Decision:
    allowed: bool
    limit_requests: int
    remaining_requests: int
    reset_requests_s: float
    limit_tokens: int
    remaining_tokens: int
    reset_tokens_s: float
    retry_after_s: float = 0.0
    reason: str | None = None  # requests | tokens

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit-Requests": str(self.limit_requests),
            "X-RateLimit-Remaining-Requests": str(max(self.remaining_requests, 0)),
            "X-RateLimit-Reset-Requests": f"{math.ceil(self.reset_requests_s)}s",
            "X-RateLimit-Limit-Tokens": str(self.limit_tokens),
            "X-RateLimit-Remaining-Tokens": str(max(self.remaining_tokens, 0)),
            "X-RateLimit-Reset-Tokens": f"{math.ceil(self.reset_tokens_s)}s",
        }


class RateLimiterBackend(Protocol):
    def admit(self, key: uuid.UUID, rpm: int, tpm: int, tokens: int, now: float) -> Decision: ...

    def adjust_tokens(self, key: uuid.UUID, delta: int, tpm: int, now: float) -> None: ...

    def release(self, key: uuid.UUID, tokens: int, tpm: int, now: float) -> None: ...

    def cleanup(self, idle_s: float, now: float) -> int: ...

    def size(self) -> int: ...


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class _KeyState:
    requests: collections.deque[float] = field(default_factory=collections.deque)
    bucket: _Bucket | None = None
    last_seen: float = 0.0


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._keys: dict[uuid.UUID, _KeyState] = {}

    def _state(self, key: uuid.UUID, now: float) -> _KeyState:
        state = self._keys.get(key)
        if state is None:
            state = self._keys[key] = _KeyState()
        state.last_seen = now
        return state

    @staticmethod
    def _refill(state: _KeyState, tpm: int, now: float) -> _Bucket:
        bucket = state.bucket
        if bucket is None:
            bucket = state.bucket = _Bucket(tokens=float(tpm), updated=now)
        rate = tpm / WINDOW_S
        bucket.tokens = min(float(tpm), bucket.tokens + (now - bucket.updated) * rate)
        bucket.updated = now
        return bucket

    def admit(self, key: uuid.UUID, rpm: int, tpm: int, tokens: int, now: float) -> Decision:
        state = self._state(key, now)
        q = state.requests
        while q and q[0] <= now - WINDOW_S:
            q.popleft()
        bucket = self._refill(state, tpm, now)
        rate = tpm / WINDOW_S
        # permintaan tunggal > kapasitas bucket diizinkan saat bucket penuh (bukan blok permanen)
        need = min(float(tokens), float(tpm))
        reset_requests = (q[0] + WINDOW_S - now) if q else 0.0
        decision = Decision(
            allowed=True,
            limit_requests=rpm,
            remaining_requests=rpm - len(q),
            reset_requests_s=reset_requests,
            limit_tokens=tpm,
            remaining_tokens=int(bucket.tokens),
            reset_tokens_s=(tpm - bucket.tokens) / rate if rate else 0.0,
        )
        if len(q) >= rpm:
            decision.allowed, decision.reason = False, "requests"
            decision.retry_after_s = max(reset_requests, 0.001)
            return decision
        if bucket.tokens < need:
            decision.allowed, decision.reason = False, "tokens"
            decision.retry_after_s = max((need - bucket.tokens) / rate, 0.001)
            return decision
        q.append(now)
        bucket.tokens -= tokens  # boleh negatif (utang) bila tokens > tpm
        decision.remaining_requests = rpm - len(q)
        decision.remaining_tokens = int(bucket.tokens)
        decision.reset_requests_s = q[0] + WINDOW_S - now
        decision.reset_tokens_s = (tpm - bucket.tokens) / rate if rate else 0.0
        return decision

    def adjust_tokens(self, key: uuid.UUID, delta: int, tpm: int, now: float) -> None:
        """delta > 0 = refund (estimasi kebesaran), delta < 0 = tambah pemakaian."""
        state = self._keys.get(key)
        if state is None:
            return
        bucket = self._refill(state, tpm, now)
        bucket.tokens = min(float(tpm), bucket.tokens + delta)

    def release(self, key: uuid.UUID, tokens: int, tpm: int, now: float) -> None:
        """Batalkan admit (request ditolak sebelum diproses): kembalikan slot & token."""
        state = self._keys.get(key)
        if state is None:
            return
        if state.requests:
            state.requests.pop()
        self.adjust_tokens(key, tokens, tpm, now)

    def cleanup(self, idle_s: float, now: float) -> int:
        stale = [k for k, s in self._keys.items() if now - s.last_seen > idle_s]
        for k in stale:
            del self._keys[k]
        return len(stale)

    def size(self) -> int:
        return len(self._keys)


@dataclass
class Reservation:
    key_id: uuid.UUID
    tokens: int
    tpm: int
    settled: bool = False


class RateLimitService:
    def __init__(
        self,
        backend: RateLimiterBackend | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backend: RateLimiterBackend = backend or InMemoryRateLimiter()
        self.clock = clock

    def check(self, auth: AuthContext, est_tokens: int) -> tuple[Reservation, dict[str, str]]:
        """Admit atau lempar RateLimited (429 + Retry-After + header X-RateLimit-*)."""
        decision = self.backend.admit(
            auth.key_id, auth.rpm_limit, auth.tpm_limit, max(est_tokens, 0), self.clock()
        )
        headers = decision.headers()
        if not decision.allowed:
            retry = max(1, math.ceil(decision.retry_after_s))
            what = "request per menit" if decision.reason == "requests" else "token per menit"
            raise RateLimited(
                f"Rate limit terlampaui ({what}); coba lagi dalam {retry} detik",
                headers={**headers, "Retry-After": str(retry)},
            )
        return Reservation(auth.key_id, max(est_tokens, 0), auth.tpm_limit), headers

    def settle(self, reservation: Reservation | None, actual_tokens: int) -> None:
        """Koreksi bucket dengan usage aktual (sekali per reservasi)."""
        if reservation is None or reservation.settled:
            return
        reservation.settled = True
        self.backend.adjust_tokens(
            reservation.key_id, reservation.tokens - actual_tokens, reservation.tpm, self.clock()
        )

    def release(self, reservation: Reservation | None) -> None:
        if reservation is None or reservation.settled:
            return
        reservation.settled = True
        self.backend.release(reservation.key_id, reservation.tokens, reservation.tpm, self.clock())

    def cleanup(self, idle_s: float = IDLE_CLEANUP_S) -> int:
        return self.backend.cleanup(idle_s, self.clock())


ratelimit_service = RateLimitService()
