"""Konteks satu request publik: identitas, caller tracing, daftar attempt (fallback), dan header
gateway. Dibuat controller (TASK-14), diisi router/service (TASK-13), dicatat usage (TASK-15)."""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.schemas.catalog import ModelConfig
from app.schemas.common import AuthContext
from app.schemas.unified import RuntimeMeta, Usage
from app.utils.errors import GatewayError
from app.utils.helper import utcnow

if TYPE_CHECKING:
    from fastapi import Request

MAX_CALLER_LEN = 128


@dataclass
class Attempt:
    attempt_no: int
    model: ModelConfig
    status: str  # success | error | cancelled
    latency_ms: int
    error: GatewayError | None = None
    runtime_meta: RuntimeMeta | None = None

    @property
    def provider_code(self) -> str:
        return self.model.provider_code

    @property
    def device(self) -> str:
        """Device aktual dari runtime bila ada; bila attempt gagal sebelum inferensi
        (mis. model_busy) dipakai device tujuan konfigurasi. `requests.device` (TASK-15) hanya
        memakai runtime_meta."""
        if self.runtime_meta is not None:
            return self.runtime_meta.device
        return self.model.device

    @property
    def error_type(self) -> str | None:
        return self.error.code if self.error else None

    @property
    def http_status(self) -> int | None:
        return self.error.http_status if self.error else None


@dataclass
class RequestCtx:
    request_id: uuid.UUID
    auth: AuthContext
    endpoint: str  # chat.completions | completions | embeddings | images.generations | images.edits
    requested_model: str
    is_stream: bool = False
    client_ip: str | None = None
    user_agent: str | None = None
    caller_task: str | None = None
    caller_agent: str | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    request_body: dict[str, Any] | None = None  # untuk payload log (bila diizinkan project)
    started: float = field(default_factory=time.perf_counter)
    created_at: datetime = field(default_factory=utcnow)  # = requests.created_at (hari UTC)
    attempts: list[Attempt] = field(default_factory=list)
    served_by: ModelConfig | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_request(
        cls,
        request: "Request",
        auth: AuthContext,
        *,
        endpoint: str,
        model: str,
        stream: bool = False,
        metadata: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> "RequestCtx":
        headers = request.headers
        state = request.scope.get("state") or {}
        raw_id = state.get("request_id")
        request_id = uuid.UUID(str(raw_id)) if raw_id else uuid.uuid4()
        client = request.client.host if request.client else None
        return cls(
            request_id=request_id,
            auth=auth,
            endpoint=endpoint,
            requested_model=model,
            is_stream=stream,
            client_ip=_client_ip(request, client),
            user_agent=headers.get("user-agent"),
            caller_task=_clip(headers.get("x-caller-task")),
            caller_agent=_clip(headers.get("x-caller-agent")),
            tags=dict(metadata or {}),
            request_body=body,
        )

    # ------------------------------------------------------------- attempts
    def record(
        self,
        model: ModelConfig,
        status: str,
        started: float,
        *,
        error: GatewayError | None = None,
        runtime_meta: RuntimeMeta | None = None,
    ) -> Attempt:
        attempt = Attempt(
            attempt_no=len(self.attempts) + 1,
            model=model,
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error=error,
            runtime_meta=runtime_meta,
        )
        self.attempts.append(attempt)
        if status == "success":
            self.served_by = model
        return attempt

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def headers(self) -> dict[str, str]:
        """Header gateway: model/provider/device yang melayani & jumlah attempt."""
        out = {"X-Request-ID": str(self.request_id), "X-Gateway-Attempts": str(len(self.attempts))}
        last = self.attempts[-1] if self.attempts else None
        if self.served_by is not None:
            out["X-Gateway-Model"] = self.served_by.alias
            out["X-Gateway-Provider"] = self.served_by.provider_code
            out["X-Gateway-Device"] = last.device if last else self.served_by.device
        if self.warnings:
            out["X-Gateway-Warning"] = ",".join(dict.fromkeys(self.warnings))
        return out


def _clip(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip()[:MAX_CALLER_LEN] or None


def _client_ip(request: "Request", fallback: str | None) -> str | None:
    from app.core.config import get_settings
    from app.utils.helper import client_ip

    try:
        return client_ip(request.scope, get_settings().trust_proxy) or fallback
    except Exception:  # noqa: BLE001
        return fallback


# Usage akhir & meta yang dikembalikan service ke controller/usage
@dataclass
class Outcome:
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    upstream_model: str | None = None
    runtime_meta: RuntimeMeta | None = None
    image_count: int = 0
    ttft_ms: int | None = None
    response_body: dict[str, Any] | None = None
    extra_tags: dict[str, Any] = field(default_factory=dict)
