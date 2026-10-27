"""SDK openai/anthropic memakai httpx2 (bukan httpx), sehingga respx tidak bisa men-patch-nya.
Mock HTTP dilakukan dengan httpx2.MockTransport yang dipasang pada klien bersama provider."""

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from app.core.config import get_settings
from app.schemas.catalog import ModelConfig, ProviderConfig


class Recorder:
    def __init__(self, handler: Callable[[httpx2.Request], httpx2.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    @property
    def last_json(self) -> dict[str, Any]:
        return json.loads(self.requests[-1].content)


def sse_body(*events: dict[str, Any] | str, event_names: list[str] | None = None) -> bytes:
    out = []
    for i, ev in enumerate(events):
        prefix = f"event: {event_names[i]}\n" if event_names else ""
        data = ev if isinstance(ev, str) else json.dumps(ev)
        out.append(f"{prefix}data: {data}\n\n")
    return "".join(out).encode()


def sse_response(body: bytes) -> httpx2.Response:
    return httpx2.Response(200, content=body, headers={"content-type": "text/event-stream"})


def json_response(
    data: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> httpx2.Response:
    return httpx2.Response(status, json=data, headers=headers)


@pytest.fixture
def mock_http():
    def make(
        handler: Callable[[httpx2.Request], httpx2.Response],
    ) -> tuple[httpx2.AsyncClient, Recorder]:
        rec = Recorder(handler)
        return httpx2.AsyncClient(transport=httpx2.MockTransport(rec)), rec

    return make


def provider_cfg(
    code: str, base_url: str | None = None, key_env: str | None = None, **kw: Any
) -> ProviderConfig:
    return ProviderConfig(
        id=uuid.uuid4(),
        code=code,
        kind=kw.pop("kind", "remote"),
        display_name=code,
        base_url=base_url,
        api_key_env=key_env,
        **kw,
    )


def model_cfg(provider: str, upstream: str, **kw: Any) -> ModelConfig:
    return ModelConfig(
        id=uuid.uuid4(),
        alias=f"{provider}/{upstream}",
        provider_code=provider,
        upstream_name=upstream,
        model_type=kw.pop("model_type", "chat"),
        **kw,
    )


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-000000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-000000")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTest000000000000000000")
    return get_settings()
