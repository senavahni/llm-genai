"""Usage, biaya & log request (TASK-15). Prinsip: tidak ada pemakaian tanpa pencatatan.

- start(): INSERT requests (pending) sebelum provider dipanggil; DB mati → 503.
- finish(): satu transaksi (requests final, request_attempts, upsert usage_daily, payload
  opsional), retry 3x, lalu fallback `logs/usage_fallback.jsonl` yang bisa di-replay.
Record dibangun sebagai data murni (JSON) dulu agar bisa ditulis ulang persis saat replay."""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, literal, select, text, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Request, RequestAttempt, UsageDaily
from app.models.request import RequestPayload
from app.schemas.catalog import ModelConfig
from app.services.context import Outcome, RequestCtx
from app.services.quota_service import quota_service
from app.services.ratelimit_service import ratelimit_service
from app.utils.errors import GatewayError, ServiceUnavailable
from app.utils.helper import utcnow
from app.utils.logger import get_logger
from app.utils.streaming import StreamOutcome

log = get_logger(__name__)

RETRY_DELAYS_S = (0.2, 0.5, 1.0)
MAX_ERROR_MESSAGE = 2000
MAX_INLINE_IMAGE = 100 * 1024
_COST_QUANT = Decimal("0.00000001")


def cost_usd(model: ModelConfig | None, outcome: Outcome) -> Decimal:
    """Decimal penuh (tanpa float): prompt (non-cache) + cache + completion + gambar."""
    if model is None:
        return Decimal(0)
    usage = outcome.usage
    cached = min(usage.cached_tokens, usage.prompt_tokens)
    cached_rate = model.config.get("cached_input_cost_per_mtok")
    cached_price = Decimal(str(cached_rate)) if cached_rate is not None else None
    uncached = usage.prompt_tokens - (cached if cached_price is not None else 0)
    total = (
        Decimal(uncached) * model.input_cost_per_mtok
        + Decimal(usage.completion_tokens) * model.output_cost_per_mtok
    )
    if cached_price is not None:
        total += Decimal(cached) * cached_price
    total = total / Decimal(1_000_000) + Decimal(outcome.image_count) * model.cost_per_image
    return total.quantize(_COST_QUANT)


def strip_images(value: Any) -> Any:
    """Gambar base64 > 100 KB di payload diganti placeholder (gambar tidak masuk log)."""
    if isinstance(value, dict):
        return {k: strip_images(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strip_images(v) for v in value]
    if isinstance(value, bytes):
        return f"<image omitted: {len(value)} bytes>"
    if isinstance(value, str) and len(value) > MAX_INLINE_IMAGE:
        if value.startswith("data:image") or _looks_base64(value):
            return f"<image omitted: {len(value) * 3 // 4} bytes>"
    return value


def _looks_base64(value: str) -> bool:
    sample = value[:2048]
    return all(c.isalnum() or c in "+/=\n\r" for c in sample)


class UsageService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession] = SessionLocal,
        fallback_path: Path | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._session_factory = session_factory
        self._fallback_path = fallback_path
        self._sleep = sleep

    @property
    def fallback_path(self) -> Path:
        return self._fallback_path or Path(get_settings().log_dir) / "usage_fallback.jsonl"

    # ---------------------------------------------------------------- start
    async def start(self, ctx: RequestCtx) -> None:
        try:
            async with self._session_factory() as session:
                session.add(
                    Request(
                        id=ctx.request_id,
                        project_id=ctx.auth.project_id,
                        api_key_id=ctx.auth.key_id,
                        endpoint=ctx.endpoint,
                        requested_model=ctx.requested_model,
                        is_stream=ctx.is_stream,
                        status="pending",
                        client_ip=ctx.client_ip,
                        user_agent=ctx.user_agent,
                        caller_task=ctx.caller_task,
                        caller_agent=ctx.caller_agent,
                        tags=ctx.tags,
                        created_at=ctx.created_at,
                    )
                )
                await session.commit()
        except Exception as exc:
            log.error("usage_start_failed", error=str(exc))
            raise ServiceUnavailable(
                "Database tidak tersedia; request ditolak agar pemakaian tetap tercatat"
            ) from exc

    # --------------------------------------------------------------- record
    def build_record(
        self,
        ctx: RequestCtx,
        outcome: Outcome | None,
        *,
        status: str,
        error: BaseException | None = None,
        http_status: int | None = None,
    ) -> dict[str, Any]:
        outcome = outcome or Outcome()
        model = ctx.served_by
        gw_error = error if isinstance(error, GatewayError) else None
        if http_status is None:
            if status == "success":
                http_status = 200
            elif status == "cancelled":
                http_status = 499
            else:
                http_status = gw_error.http_status if gw_error else 500
        tags = dict(ctx.tags)
        tags.update(outcome.extra_tags)
        if outcome.usage.estimated:
            tags["usage_estimated"] = True
        meta = outcome.runtime_meta
        device: str | None = None
        if model is not None:
            if model.is_local:
                device = meta.device if meta else None
                if meta is None and status == "success":
                    # bukti NF9 (tanpa CPU) diambil dari runtime, bukan konfigurasi
                    tags["runtime_meta_missing"] = True
                    log.warning("runtime_meta_missing", model=model.alias)
            else:
                device = "remote"
        if meta is not None and meta.warnings:
            tags["runtime_warnings"] = meta.warnings
        if ctx.warnings:
            tags["gateway_warnings"] = list(dict.fromkeys(ctx.warnings))
        message = None
        if error is not None:
            message = (gw_error.message if gw_error else f"{type(error).__name__}: {error}")[
                :MAX_ERROR_MESSAGE
            ]
        usage = outcome.usage
        record: dict[str, Any] = {
            "request_id": str(ctx.request_id),
            "project_id": str(ctx.auth.project_id) if ctx.auth.project_id else None,
            "created_at": ctx.created_at.isoformat(),
            "requested_model": ctx.requested_model,
            "status": status,
            "http_status": http_status,
            "error_type": gw_error.code if gw_error else (type(error).__name__ if error else None),
            "error_message": message,
            "finish_reason": outcome.finish_reason,
            "resolved_model_id": str(model.id) if model else None,
            "model_alias": model.alias if model else ctx.requested_model,
            "provider_code": model.provider_code if model else "none",
            "upstream_model": outcome.upstream_model or (model.upstream_name if model else None),
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cached_tokens": usage.cached_tokens,
            "image_count": outcome.image_count,
            "device": device,
            "load_ms": meta.load_ms if meta else None,
            "queue_ms": meta.queue_ms if meta else None,
            # token yang sudah dihasilkan tetap dibayar walau stream gagal/dibatalkan
            "cost_usd": str(cost_usd(model, outcome)),
            "latency_ms": ctx.elapsed_ms,
            "ttft_ms": outcome.ttft_ms,
            "attempts": [
                {
                    "attempt_no": a.attempt_no,
                    "model_id": str(a.model.id),
                    "provider_code": a.provider_code,
                    "device": a.device,
                    "status": a.status,
                    "http_status": a.http_status,
                    "error_type": a.error_type,
                    "error_message": a.error.message[:MAX_ERROR_MESSAGE] if a.error else None,
                    "latency_ms": a.latency_ms,
                }
                for a in ctx.attempts
            ],
            "tags": tags,
            "completed_at": utcnow().isoformat(),
            "payload": None,
        }
        if ctx.auth.log_payloads and ctx.request_body is not None:
            expires = utcnow() + timedelta(days=max(ctx.auth.payload_retention_days, 0))
            record["payload"] = {
                "request_body": strip_images(ctx.request_body),
                "response_body": strip_images(outcome.response_body)
                if outcome.response_body is not None
                else None,
                "expires_at": expires.isoformat(),
            }
        return record

    # ---------------------------------------------------------------- finish
    async def finish(
        self,
        ctx: RequestCtx,
        outcome: Outcome | None,
        *,
        status: str,
        error: BaseException | None = None,
        http_status: int | None = None,
    ) -> None:
        record = self.build_record(
            ctx, outcome, status=status, error=error, http_status=http_status
        )
        # sinkron & sebelum I/O DB: koreksi TPM dengan usage aktual + kuota berjalan
        tokens = record["prompt_tokens"] + record["completion_tokens"]
        ratelimit_service.settle(ctx.reservation, tokens)
        quota_service.record(
            ctx.auth.project_id,
            tokens=tokens,
            images=record["image_count"],
            cost=Decimal(record["cost_usd"]),
        )
        await self.persist(record)

    def finish_stream(
        self, ctx: RequestCtx, outcome: Outcome
    ) -> Callable[[StreamOutcome], Awaitable[None]]:
        """Callback on_finish untuk guarded_stream (dipanggil tepat sekali)."""

        async def _on_finish(stream: StreamOutcome) -> None:
            if outcome.ttft_ms is None and stream.ttft_ms is not None:
                outcome.ttft_ms = stream.ttft_ms
            await self.finish(ctx, outcome, status=stream.status, error=stream.error)

        return _on_finish

    async def persist(self, record: dict[str, Any]) -> None:
        last: Exception | None = None
        for delay in (0.0, *RETRY_DELAYS_S):
            if delay:
                await self._sleep(delay)
            try:
                async with self._session_factory() as session:
                    await write_record(session, record)
                    await session.commit()
                return
            except Exception as exc:  # noqa: BLE001 - dicoba ulang lalu fallback file
                last = exc
                log.warning("usage_write_retry", request_id=record["request_id"], error=str(exc))
        log.error("usage_write_failed_fallback", request_id=record["request_id"], error=str(last))
        await asyncio.to_thread(self._append_fallback, record)

    def _append_fallback(self, record: dict[str, Any]) -> None:
        path = self.fallback_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def replay(self) -> tuple[int, int]:
        """Tulis ulang record fallback ke DB. Yang gagal tetap tersimpan untuk dicoba lagi."""
        path = self.fallback_path
        if not path.exists():
            return 0, 0
        processing = path.with_suffix(".replaying.jsonl")
        path.replace(processing)
        ok, failed = 0, []
        for line in processing.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            try:
                async with self._session_factory() as session:
                    await write_record(session, record)
                    await session.commit()
                ok += 1
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "usage_replay_failed", request_id=record.get("request_id"), error=str(exc)
                )
                failed.append(line)
        if failed:
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(failed) + "\n")
        processing.unlink()
        return ok, len(failed)

    # --------------------------------------------------------------- sweeper
    async def sweep_orphans(self, older_than: timedelta = timedelta(minutes=10)) -> int:
        """Request `pending` terlalu lama (proses mati di tengah) → error `orphaned`, dihitung
        ke usage_daily sebagai error."""
        cutoff = utcnow() - older_than
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    update(Request)
                    .where(Request.status == "pending", Request.created_at < cutoff)
                    .values(
                        status="error",
                        error_type="orphaned",
                        error_message="request tidak diselesaikan (proses berhenti?)",
                        completed_at=utcnow(),
                    )
                    .returning(Request.project_id, Request.created_at, Request.requested_model)
                )
            ).all()
            for project_id, created_at, requested in rows:
                if project_id is not None:
                    await _upsert_daily(
                        session,
                        day=_utc_day(created_at),
                        project_id=project_id,
                        model_alias=requested,
                        provider_code="none",
                        success=False,
                    )
            await session.commit()
        if rows:
            log.warning("usage_orphans_swept", count=len(rows))
        return len(rows)

    # ---------------------------------------------------------- verifikasi
    async def verify(self, day: date) -> list[dict[str, Any]]:
        """Per project: jumlah baris requests final vs Σ usage_daily.request_count (harus 0)."""
        query = text(
            """
            WITH r AS (
                SELECT project_id, count(*) AS req_rows,
                       COALESCE(sum(image_count), 0) AS req_images
                FROM requests
                WHERE status <> 'pending' AND project_id IS NOT NULL
                  AND (created_at AT TIME ZONE 'UTC')::date = :day
                GROUP BY project_id
            ), u AS (
                SELECT project_id, sum(request_count) AS agg_rows, sum(image_count) AS agg_images
                FROM usage_daily WHERE day = :day GROUP BY project_id
            )
            SELECT COALESCE(r.project_id, u.project_id) AS project_id,
                   COALESCE(r.req_rows, 0) AS req_rows, COALESCE(u.agg_rows, 0) AS agg_rows,
                   COALESCE(r.req_images, 0) AS req_images,
                   COALESCE(u.agg_images, 0) AS agg_images
            FROM r FULL OUTER JOIN u ON r.project_id = u.project_id
            ORDER BY 1
            """
        )
        async with self._session_factory() as session:
            rows = (await session.execute(query, {"day": day})).mappings().all()
        return [
            {
                "project_id": str(r["project_id"]),
                "req_rows": int(r["req_rows"]),
                "agg_rows": int(r["agg_rows"]),
                "diff": int(r["req_rows"]) - int(r["agg_rows"]),
                "image_diff": int(r["req_images"]) - int(r["agg_images"]),
            }
            for r in rows
        ]


# ------------------------------------------------------------------ penulisan
def _clip(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


def _utc_day(value: datetime) -> date:
    from datetime import UTC

    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UTC).date()


async def _upsert_daily(
    session: AsyncSession,
    *,
    day: date,
    project_id: uuid.UUID,
    model_alias: str,
    provider_code: str,
    success: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    image_count: int = 0,
    cost: Decimal = Decimal(0),
) -> None:
    values = {
        "request_count": 1,
        "success_count": 1 if success else 0,
        "error_count": 0 if success else 1,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "image_count": image_count,
        "cost_usd": cost,
    }
    stmt = insert(UsageDaily).values(
        day=day,
        project_id=project_id,
        model_alias=model_alias[:128],
        provider_code=provider_code[:32],
        **values,
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["day", "project_id", "model_alias", "provider_code"],
            set_={k: getattr(UsageDaily, k) + getattr(stmt.excluded, k) for k in values},
        )
    )


async def write_record(session: AsyncSession, record: dict[str, Any]) -> None:
    """Satu transaksi (commit oleh pemanggil). Idempoten per request: attempts/payload lama
    dihapus dulu sehingga replay tidak menggandakan; usage_daily hanya ditambah bila request
    masih pending (belum pernah difinalisasi)."""
    request_id = uuid.UUID(record["request_id"])
    created_at = datetime.fromisoformat(record["created_at"])
    current = (
        await session.execute(select(Request.status).where(Request.id == request_id))
    ).scalar_one_or_none()
    if current is None:
        raise RuntimeError(f"request {request_id} tidak ada (start() belum tercatat?)")
    first_finalization = current == "pending"
    total_tokens = record["prompt_tokens"] + record["completion_tokens"]
    await session.execute(
        update(Request)
        .where(Request.id == request_id)
        .values(
            status=record["status"],
            http_status=record["http_status"],
            error_type=_clip(record["error_type"], 64),
            error_message=record["error_message"],
            finish_reason=_clip(record["finish_reason"], 32),
            resolved_model_id=uuid.UUID(record["resolved_model_id"])
            if record["resolved_model_id"]
            else None,
            provider_code=record["provider_code"] if record["provider_code"] != "none" else None,
            upstream_model=record["upstream_model"],
            prompt_tokens=record["prompt_tokens"],
            completion_tokens=record["completion_tokens"],
            total_tokens=total_tokens,
            cached_tokens=record["cached_tokens"],
            image_count=record["image_count"],
            device=record["device"],
            load_ms=record["load_ms"],
            queue_ms=record["queue_ms"],
            cost_usd=Decimal(record["cost_usd"]),
            latency_ms=record["latency_ms"],
            ttft_ms=record["ttft_ms"],
            attempts=len(record["attempts"]),
            tags=Request.tags.op("||")(literal(record["tags"], JSONB)),
            completed_at=datetime.fromisoformat(record["completed_at"]),
        )
    )
    await session.execute(delete(RequestAttempt).where(RequestAttempt.request_id == request_id))
    if record["attempts"]:
        await session.execute(
            insert(RequestAttempt),
            [
                {
                    **a,
                    "request_id": request_id,
                    "model_id": uuid.UUID(a["model_id"]) if a["model_id"] else None,
                    "error_type": _clip(a["error_type"], 64),
                }
                for a in record["attempts"]
            ],
        )
    if first_finalization and record["project_id"]:
        await _upsert_daily(
            session,
            day=_utc_day(created_at),
            project_id=uuid.UUID(record["project_id"]),
            model_alias=record["model_alias"],
            provider_code=record["provider_code"],
            success=record["status"] == "success",
            prompt_tokens=record["prompt_tokens"],
            completion_tokens=record["completion_tokens"],
            image_count=record["image_count"],
            cost=Decimal(record["cost_usd"]),
        )
    payload = record.get("payload")
    if payload:
        await session.execute(
            insert(RequestPayload)
            .values(
                request_id=request_id,
                request_body=payload["request_body"],
                response_body=payload["response_body"],
                expires_at=datetime.fromisoformat(payload["expires_at"]),
            )
            .on_conflict_do_nothing(index_elements=["request_id"])
        )


usage_service = UsageService()
