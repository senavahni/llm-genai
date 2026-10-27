import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel

from app.core.config import load_settings
from app.main import create_app
from app.utils import errors as e


@pytest.mark.parametrize(
    ("cls", "status", "etype", "code", "retryable"),
    [
        (e.InvalidRequestError, 400, "invalid_request_error", "invalid_request", False),
        (e.CapabilityNotSupported, 400, "invalid_request_error", "capability_not_supported", False),
        (e.AuthenticationError, 401, "authentication_error", "invalid_api_key", False),
        (e.PermissionDenied, 403, "permission_error", "scope_denied", False),
        (e.ModelNotAllowed, 403, "permission_error", "model_not_allowed", False),
        (e.ProjectSuspended, 403, "permission_error", "project_suspended", False),
        (e.ModelNotFound, 404, "invalid_request_error", "model_not_found", False),
        (e.RateLimited, 429, "rate_limit_error", "rate_limited", False),
        (e.QuotaExceeded, 429, "rate_limit_error", "quota_exceeded", False),
        (e.UpstreamError, 502, "upstream_error", "upstream_error", True),
        (e.UpstreamTimeout, 504, "upstream_error", "upstream_timeout", True),
        (e.UpstreamRateLimited, 429, "rate_limit_error", "upstream_rate_limited", True),
        (e.UpstreamBadRequest, 400, "invalid_request_error", "upstream_bad_request", False),
        (e.ServiceUnavailable, 503, "server_error", "service_unavailable", False),
        (e.ModelBusy, 503, "upstream_error", "model_busy", True),
        (e.DeviceOOM, 503, "upstream_error", "device_oom", True),
        (e.DeviceUnavailable, 503, "upstream_error", "device_unavailable", True),
        (e.UnsupportedSize, 400, "invalid_request_error", "unsupported_size", False),
        (e.ImageNotFound, 404, "invalid_request_error", "image_not_found", False),
        (e.PayloadTooLarge, 413, "invalid_request_error", "payload_too_large", False),
    ],
)
def test_error_mapping(cls, status, etype, code, retryable):
    err = cls("boom")
    assert (err.http_status, err.error_type, err.code, err.retryable) == (
        status,
        etype,
        code,
        retryable,
    )
    body = err.to_openai_dict("rid-1")["error"]
    assert body == {
        "message": "boom",
        "type": etype,
        "code": code,
        "param": err.param,
        "request_id": "rid-1",
    }


def test_default_params():
    assert e.ModelNotFound("x").param == "model"
    assert e.UnsupportedSize("x").param == "size"
    assert e.ModelNotFound("x", param="other").param == "other"
    assert issubclass(e.ModelBusy, e.UpstreamError)
    assert issubclass(e.ModelNotAllowed, e.PermissionDenied)


class _Body(BaseModel):
    model: str
    n: int


def _app(max_body_mb: int = 20) -> FastAPI:
    app = create_app(load_settings(max_body_mb=max_body_mb))

    @app.get("/test/model-not-found")
    async def _mnf() -> None:
        raise e.ModelNotFound("Model 'x' tidak ditemukan")

    @app.get("/test/rate-limited")
    async def _rl() -> None:
        raise e.RateLimited("pelan-pelan", headers={"Retry-After": "7"})

    @app.get("/test/crash")
    async def _crash() -> None:
        raise RuntimeError("secret internal detail")

    @app.post("/test/validate")
    async def _validate(body: _Body) -> dict[str, int]:
        return {"n": body.n}

    @app.post("/test/echo")
    async def _echo(request: Request) -> dict[str, int]:
        return {"len": len(await request.body())}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_model_not_found_is_openai_404_with_request_id():
    async with _client(_app()) as c:
        r = await c.get("/test/model-not-found")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "model_not_found"
    assert err["type"] == "invalid_request_error"
    assert err["param"] == "model"
    assert err["request_id"] == r.headers["x-request-id"]
    uuid.UUID(err["request_id"])


async def test_incoming_request_id_is_reused():
    rid = str(uuid.uuid4())
    async with _client(_app()) as c:
        r = await c.get("/test/model-not-found", headers={"X-Request-ID": rid})
    assert r.headers["x-request-id"] == rid
    assert r.json()["error"]["request_id"] == rid


async def test_invalid_incoming_request_id_is_replaced():
    async with _client(_app()) as c:
        r = await c.get("/health/live", headers={"X-Request-ID": "not-a-uuid"})
    assert r.headers["x-request-id"] != "not-a-uuid"
    uuid.UUID(r.headers["x-request-id"])


async def test_error_headers_are_forwarded():
    async with _client(_app()) as c:
        r = await c.get("/test/rate-limited")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "7"


async def test_validation_error_is_400_with_param():
    async with _client(_app()) as c:
        r = await c.post("/test/validate", json={"model": "x", "n": "abc"})
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "invalid_request"
    assert err["param"] == "n"


async def test_unhandled_exception_is_generic_500():
    async with _client(_app()) as c:
        r = await c.get("/test/crash")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "internal_error"
    assert "secret internal detail" not in r.text
    assert err["request_id"] == r.headers["x-request-id"]


async def test_unknown_path_is_openai_404():
    async with _client(_app()) as c:
        r = await c.get("/does-not-exist")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_body_over_limit_by_content_length_is_413():
    async with _client(_app(max_body_mb=1)) as c:
        r = await c.post("/test/echo", content=b"x" * (1024 * 1024 + 1))
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
    assert r.headers["x-request-id"]


async def test_body_over_limit_chunked_is_413():
    async def gen():
        for _ in range(3):
            yield b"x" * (512 * 1024)

    async with _client(_app(max_body_mb=1)) as c:
        r = await c.post("/test/echo", content=gen())
    assert r.status_code == 413


async def test_body_under_limit_passes():
    async with _client(_app(max_body_mb=1)) as c:
        r = await c.post("/test/echo", content=b"x" * 1000)
    assert r.status_code == 200
    assert r.json() == {"len": 1000}


async def test_docs_only_in_dev():
    async with _client(create_app(load_settings(app_env="prod"))) as c:
        assert (await c.get("/docs")).status_code == 404
    async with _client(create_app(load_settings(app_env="dev"))) as c:
        assert (await c.get("/docs")).status_code == 200
