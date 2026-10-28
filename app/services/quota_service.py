"""Kuota project harian/bulanan (TASK-16), dicek SEBELUM provider dipanggil.

Pemakaian berjalan = agregat `usage_daily` (cache 30 detik) + penambahan in-memory dari request
yang selesai sejak cache dibuat, agar tidak kebobolan dalam jendela cache. Soft limit: request yang
sudah berjalan boleh selesai walau melewati batas."""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models import Quota, UsageDaily
from app.utils.errors import QuotaExceeded

QUOTA_CACHE_S = 60.0
USAGE_CACHE_S = 30.0


@dataclass(frozen=True, slots=True)
class QuotaRule:
    period: str  # daily | monthly
    max_requests: int | None
    max_tokens: int | None
    max_images: int | None
    max_cost_usd: Decimal | None


@dataclass
class Totals:
    requests: int = 0
    tokens: int = 0
    images: int = 0
    cost: Decimal = field(default_factory=lambda: Decimal(0))

    def add(self, other: "Totals") -> "Totals":
        return Totals(
            self.requests + other.requests,
            self.tokens + other.tokens,
            self.images + other.images,
            self.cost + other.cost,
        )


@dataclass
class _UsageEntry:
    period_start: date
    base: Totals
    delta: Totals
    loaded: float


def period_start(period: str, now: datetime) -> date:
    today = now.astimezone(UTC).date()
    return today if period == "daily" else today.replace(day=1)


def seconds_to_reset(period: str, now: datetime) -> int:
    now = now.astimezone(UTC)
    if period == "daily":
        nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
    else:
        first = now.date().replace(day=1)
        nxt_month = (first + timedelta(days=32)).replace(day=1)
        nxt = datetime.combine(nxt_month, datetime.min.time(), UTC)
    return max(1, int((nxt - now).total_seconds()))


class QuotaService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession] = SessionLocal,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        self.now, self.clock = now, clock
        self._rules: dict[uuid.UUID, tuple[float, list[QuotaRule]]] = {}
        self._usage: dict[tuple[uuid.UUID, str], _UsageEntry] = {}

    def invalidate(self, project_id: uuid.UUID | None = None) -> None:
        if project_id is None:
            self._rules.clear()
            self._usage.clear()
            return
        self._rules.pop(project_id, None)
        for k in [k for k in self._usage if k[0] == project_id]:
            del self._usage[k]

    async def _rules_for(self, project_id: uuid.UUID) -> list[QuotaRule]:
        hit = self._rules.get(project_id)
        if hit and self.clock() - hit[0] < QUOTA_CACHE_S:
            return hit[1]
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(Quota).where(
                            Quota.project_id == project_id, Quota.is_enabled.is_(True)
                        )
                    )
                )
                .scalars()
                .all()
            )
        rules = [
            QuotaRule(r.period, r.max_requests, r.max_tokens, r.max_images, r.max_cost_usd)
            for r in rows
        ]
        self._rules[project_id] = (self.clock(), rules)
        return rules

    async def _usage_for(self, project_id: uuid.UUID, period: str) -> Totals:
        start = period_start(period, self.now())
        key = (project_id, period)
        entry = self._usage.get(key)
        if (
            entry is not None
            and entry.period_start == start
            and self.clock() - entry.loaded < USAGE_CACHE_S
        ):
            return entry.base.add(entry.delta)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(UsageDaily.request_count), 0),
                        func.coalesce(
                            func.sum(UsageDaily.prompt_tokens + UsageDaily.completion_tokens), 0
                        ),
                        func.coalesce(func.sum(UsageDaily.image_count), 0),
                        func.coalesce(func.sum(UsageDaily.cost_usd), 0),
                    ).where(UsageDaily.project_id == project_id, UsageDaily.day >= start)
                )
            ).one()
        base = Totals(int(row[0]), int(row[1]), int(row[2]), Decimal(row[3]))
        self._usage[key] = _UsageEntry(start, base, Totals(), self.clock())
        return base

    async def check(self, project_id: uuid.UUID | None, images: int = 0) -> None:
        if project_id is None:
            return  # key admin tanpa project: tidak berkuota
        for rule in await self._rules_for(project_id):
            used = await self._usage_for(project_id, rule.period)
            exceeded = None
            if rule.max_requests is not None and used.requests >= rule.max_requests:
                exceeded = f"requests {used.requests}/{rule.max_requests}"
            elif rule.max_tokens is not None and used.tokens >= rule.max_tokens:
                exceeded = f"tokens {used.tokens}/{rule.max_tokens}"
            elif rule.max_images is not None and used.images + images > rule.max_images:
                exceeded = f"images {used.images}+{images}/{rule.max_images}"
            elif rule.max_cost_usd is not None and used.cost >= rule.max_cost_usd:
                exceeded = f"cost_usd {used.cost:.4f}/{rule.max_cost_usd}"
            if exceeded:
                retry = seconds_to_reset(rule.period, self.now())
                period = "harian" if rule.period == "daily" else "bulanan"
                raise QuotaExceeded(
                    f"Kuota {period} project habis ({exceeded}); reset dalam {retry} detik (UTC)",
                    headers={"Retry-After": str(retry)},
                )

    def record(
        self,
        project_id: uuid.UUID | None,
        *,
        tokens: int = 0,
        images: int = 0,
        cost: Decimal = Decimal(0),
    ) -> None:
        """Tambahkan request yang baru selesai ke cache berjalan (sebelum cache disegarkan)."""
        if project_id is None:
            return
        for (pid, _period), entry in self._usage.items():
            if pid == project_id:
                entry.delta = entry.delta.add(Totals(1, tokens, images, cost))


quota_service = QuotaService()
