import json
import logging
import time

import httpx
import pytest

from app.core.config import load_settings
from app.main import create_app
from app.utils.logger import (
    REDACTED,
    get_logger,
    redact_value,
    setup_logging,
    shutdown_logging,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Authorization: Bearer lgw_ab12cd34_secret",
            f"Authorization: Bearer lgw_ab12cd34_{REDACTED}",
        ),
        ("key=sk-proj-abcdefghij1234567890", f"key={REDACTED}"),
        ("key=sk-ant-api03-abc_DEF-123", f"key={REDACTED}"),
        ("gemini AIzaSyA1234567890abcdefghijklmnop", f"gemini {REDACTED}"),
        ("Bearer some.opaque-token_value", f"Bearer {REDACTED}"),
        ("nothing sensitive here", "nothing sensitive here"),
        ("prompt_tokens=12 sk-short", "prompt_tokens=12 sk-short"),
    ],
)
def test_value_patterns(raw, expected):
    assert redact_value(raw) == expected


def test_sensitive_keys_and_recursion():
    data = {
        "Authorization": "Bearer abc",
        "headers": {"X-API-Key": "whatever", "x-runtime-token": "t", "accept": "json"},
        "items": [{"password": "p"}, {"note": "use lgw_k3m9x2qa_AAAABBBBCCCC please"}],
        "key_hash": "f" * 64,
        "openai_api_key": "abc",
        "prompt_tokens": 10,
        "key_prefix": "lgw_k3m9x2qa",
        "token": None,
    }
    out = redact_value(data)
    assert out["Authorization"] == REDACTED
    assert out["headers"] == {
        "X-API-Key": REDACTED,
        "x-runtime-token": REDACTED,
        "accept": "json",
    }
    assert out["items"][0]["password"] == REDACTED
    assert out["items"][1]["note"] == f"use lgw_k3m9x2qa_{REDACTED} please"
    assert out["key_hash"] == REDACTED
    assert out["openai_api_key"] == REDACTED
    assert out["prompt_tokens"] == 10
    assert out["key_prefix"] == "lgw_k3m9x2qa"
    assert out["token"] is None


@pytest.fixture
def log_dir(tmp_path):
    settings = load_settings(log_dir=str(tmp_path), app_env="prod", log_level="INFO")
    yield tmp_path, settings
    shutdown_logging()


def _read_json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_files_are_json_and_redacted(log_dir):
    tmp_path, settings = log_dir
    setup_logging(settings, console=False)
    log = get_logger("test")
    log.info("upstream_call", headers={"authorization": "Bearer lgw_ab12cd34_secret"},
             raw="Authorization: Bearer lgw_ab12cd34_secret")
    logging.getLogger("foreign.stdlib").error("stdlib error with sk-proj-abcdefghij1234567890")
    shutdown_logging()

    app_lines = _read_json_lines(tmp_path / "app.log")
    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert "lgw_ab12cd34_secret" not in text
    assert "sk-proj-abcdefghij1234567890" not in text
    rec = next(r for r in app_lines if r["event"] == "upstream_call")
    assert rec["headers"]["authorization"] == REDACTED
    assert rec["raw"] == f"Authorization: Bearer lgw_ab12cd34_{REDACTED}"
    assert {"ts", "level", "logger", "event"} <= rec.keys()

    errors = _read_json_lines(tmp_path / "error.log")
    assert [r["logger"] for r in errors] == ["foreign.stdlib"]


def test_runtime_component_files(log_dir):
    tmp_path, settings = log_dir
    # log native ditulis level DEBUG: hanya tampil bila LOG_LEVEL=DEBUG
    setup_logging(settings.model_copy(update={"log_level": "DEBUG"}), component="runtime",
                  console=False)
    get_logger("runtime.native").debug("llama_cpp_verbose_line")
    get_logger("runtime").error("device_error")
    shutdown_logging()
    assert "llama_cpp_verbose_line" in (tmp_path / "runtime.log").read_text(encoding="utf-8")
    assert "device_error" in (tmp_path / "runtime-error.log").read_text(encoding="utf-8")
    assert not (tmp_path / "app.log").exists()
    assert not (tmp_path / "access.log").exists()


async def test_access_log_one_line_per_request(log_dir):
    tmp_path, settings = log_dir
    setup_logging(settings, console=False)
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        responses = [await c.get("/health/live", headers={"user-agent": "ua-test"})
                     for _ in range(3)]
        responses.append(await c.get("/missing"))
    shutdown_logging()

    lines = _read_json_lines(tmp_path / "access.log")
    assert len(lines) == 4
    for r, line in zip(responses, lines, strict=True):
        assert line["request_id"] == r.headers["x-request-id"]
        assert line["status"] == r.status_code
        assert line["bytes_sent"] == len(r.content)
        assert line["method"] == "GET"
        assert line["latency_ms"] >= 0
    assert lines[0]["user_agent"] == "ua-test"
    # access log tidak bocor ke app.log (file dibuat lazy: bisa belum ada)
    app_log = tmp_path / "app.log"
    assert not app_log.exists() or "http_request" not in app_log.read_text(encoding="utf-8")


def test_rotation(log_dir):
    tmp_path, settings = log_dir
    setup_logging(settings, console=False, rotate_when="S")
    log = get_logger("rot")
    log.info("first")
    time.sleep(1.2)
    log.info("second")
    shutdown_logging()
    rotated = [p.name for p in tmp_path.glob("app.log.*")]
    assert rotated, list(tmp_path.iterdir())
