import json

from runtime.services.event_service import EventService


class _BrokenSession:
    async def __aenter__(self):
        raise ConnectionError("db down")

    async def __aexit__(self, *exc):
        return False


async def test_record_falls_back_to_jsonl_when_db_down(tmp_path):
    path = tmp_path / "runtime_events_fallback.jsonl"
    svc = EventService(path, session_factory=_BrokenSession)
    svc.record(
        "load",
        device="gpu",
        model_alias="local/x",
        duration_ms=12,
        request_id="0190f0b4-0000-7000-8000-000000000000",
        details={"n_ctx": 4096},
    )
    svc.record("runtime_start", device="npu")
    await svc.drain()
    # penulisan fallback paralel (thread) → urutan baris tidak dijamin; tiap baris punya created_at
    rows = {r["event"]: r for r in map(json.loads, path.read_text().splitlines())}
    assert sorted(rows) == ["load", "runtime_start"]
    load = rows["load"]
    assert load["model_alias"] == "local/x" and load["details"] == {"n_ctx": 4096}
    assert load["request_id"] == "0190f0b4-0000-7000-8000-000000000000"
    assert load["created_at"]
