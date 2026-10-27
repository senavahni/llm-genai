"""Unit test DeviceManager tanpa hardware (fake backend + jam palsu untuk min residency)."""

import asyncio

import pytest

from app.utils.errors import DeviceOOM, DeviceUnavailable, ModelBusy, ModelLoadFailed
from runtime.device.manager import DeviceManager
from tests.fakes.fake_backend import FakeBackend, spec

PINNED = spec("local/coder-1.5b", 1300, pinned=True)
MODEL_A = spec("local/qwen-7b", 5400)
MODEL_B = spec("local/coder-7b", 5600)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    def record(self, event: str, **kw) -> None:
        self.items.append((event, kw))

    def names(self, *, alias: str | None = None) -> list[str]:
        return [n for n, kw in self.items if alias is None or kw.get("model_alias") == alias]


def _manager(clock=None, events=None, **kw) -> DeviceManager:
    return DeviceManager(
        "gpu",
        kw.pop("budget_mb", 7200),
        min_residency_s=kw.pop("min_residency_s", 60),
        queue_timeout_s=kw.pop("queue_timeout_s", 0.5),
        backend_factory=FakeBackend,
        events=events,
        clock=clock or Clock(),
        **kw,
    )


async def _use(m: DeviceManager, s) -> None:
    async with m.acquire(s, "rid") as lease:
        assert lease.backend.is_loaded()


async def test_lru_evict_after_min_residency_pinned_never_evicted():
    clock, events = Clock(), Events()
    m = _manager(clock, events)
    await m.load(PINNED, reason="warmup")
    await _use(m, MODEL_A)
    assert m.used_mb == 6700
    clock.now += 61  # lewat min residency
    events.items.clear()
    await _use(m, MODEL_B)
    assert sorted(m.loaded_aliases()) == ["local/coder-1.5b", "local/coder-7b"]
    assert m.used_mb == 6900 <= m.budget_mb
    assert events.names() == ["evict", "load"]
    assert events.items[0][1]["model_alias"] == "local/qwen-7b"
    assert events.items[0][1]["reason"] == "lru_evict_for:local/coder-7b"
    assert "evict" not in events.names(alias="local/coder-1.5b")


async def test_min_residency_blocks_eviction_then_model_busy():
    clock, events = Clock(), Events()
    m = _manager(clock, events, queue_timeout_s=0.2)
    await m.load(PINNED)
    await _use(m, MODEL_A)
    with pytest.raises(ModelBusy):  # A baru dimuat (< 60 dtk) → tidak boleh di-evict
        await _use(m, MODEL_B)
    assert m.is_loaded("local/qwen-7b")
    assert "queue_timeout" in events.names()


async def test_busy_model_not_evicted_waits_then_model_busy():
    clock, events = Clock(), Events()
    m = _manager(clock, events, queue_timeout_s=0.3)
    await m.load(PINNED)
    clock.now += 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def hold_a():
        async with m.acquire(MODEL_A, "a"):
            started.set()
            await release.wait()

    holder = asyncio.ensure_future(hold_a())
    await started.wait()
    clock.now += 120  # residency lewat, tetapi A sedang melayani request
    with pytest.raises(ModelBusy):
        await _use(m, MODEL_B)
    assert m.is_loaded("local/qwen-7b")
    release.set()
    await holder
    # setelah A idle, B bisa dimuat (A di-evict)
    await _use(m, MODEL_B)
    assert m.is_loaded("local/coder-7b") and not m.is_loaded("local/qwen-7b")


async def test_waiting_request_gets_model_when_holder_finishes():
    clock = Clock()
    m = _manager(clock, queue_timeout_s=2)
    await m.load(PINNED)
    release = asyncio.Event()
    started = asyncio.Event()

    async def hold_a():
        async with m.acquire(MODEL_A, "a"):
            started.set()
            await release.wait()

    holder = asyncio.ensure_future(hold_a())
    await started.wait()
    clock.now += 120
    waiter = asyncio.ensure_future(_use(m, MODEL_B))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    release.set()
    await holder
    await asyncio.wait_for(waiter, 1)
    assert m.is_loaded("local/coder-7b")


async def test_per_model_queue_semaphore():
    m = _manager(queue_timeout_s=0.2)
    release = asyncio.Event()
    started = asyncio.Event()

    async def hold():
        async with m.acquire(PINNED, "x"):
            started.set()
            await release.wait()

    t = asyncio.ensure_future(hold())
    await started.wait()
    assert m.status().models[0]["active"] == 1
    with pytest.raises(ModelBusy):  # replicas=1 → request kedua antre lalu timeout
        await _use(m, PINNED)
    release.set()
    await t
    await _use(m, PINNED)


async def test_oom_retries_with_ctx_fallback():
    events = Events()
    m = _manager(events=events)
    s = spec(
        "local/big",
        3000,
        n_ctx=8192,
        auto_reduce_ctx=True,
        ctx_fallback=[8192, 4096],
        oom_above_ctx=4096,
    )
    async with m.acquire(s, "r") as lease:
        assert lease.spec.n_ctx == 4096
    assert events.names() == ["oom", "load"]
    assert events.items[0][1]["details"] == {"n_ctx": 8192, "retry_n_ctx": 4096}


async def test_oom_without_fallback_raises_device_oom_and_no_crash():
    events = Events()
    m = _manager(events=events)
    s = spec(
        "local/big",
        3000,
        n_ctx=8192,
        oom_above_ctx=1024,
        auto_reduce_ctx=True,
        ctx_fallback=[8192, 4096],
    )
    with pytest.raises(DeviceOOM) as info:
        await _use(m, s)
    assert info.value.retryable
    assert events.names() == ["oom", "oom"]
    assert m.used_mb == 0
    await _use(m, PINNED)  # manager tetap berfungsi


async def test_cpu_rejected_unless_allowed():
    events = Events()
    s = spec("local/x", 1000, report_device="cpu")
    m = _manager(events=events)
    with pytest.raises(DeviceUnavailable):
        await _use(m, s)
    assert events.items[-1][0] == "load_failed"
    assert events.items[-1][1]["reason"] == "cpu_not_allowed"
    assert not m.is_loaded("local/x")
    allowed = _manager(allow_cpu_fallback=True)
    await _use(allowed, s)


async def test_vram_over_budget_and_load_failure():
    events = Events()
    m = _manager(events=events)
    with pytest.raises(ModelLoadFailed, match="melebihi budget"):
        await _use(m, spec("local/huge", 9000))
    with pytest.raises(ModelLoadFailed, match="missing.gguf"):
        await _use(m, spec("local/missing", 100, fail_load="missing.gguf"))
    assert events.names() == ["load_failed", "load_failed"]


async def test_backend_unavailable_records_load_failed():
    events = Events()

    def no_backend(_spec):
        raise ModelLoadFailed("backend llama_cpp_python belum tersedia")

    m = DeviceManager("gpu", 7200, backend_factory=no_backend, events=events)
    with pytest.raises(ModelLoadFailed):
        await _use(m, PINNED)
    assert events.names() == ["load_failed"]


async def test_concurrent_requests_load_once():
    events = Events()
    m = _manager(events=events, queue_timeout_s=2)
    s = spec("local/slow", 1000, load_delay_s=0.1)
    await asyncio.gather(*(_use(m, s) for _ in range(5)))
    assert events.names() == ["load"]


async def test_native_calls_run_in_device_thread_pool():
    m = _manager()
    async with m.acquire(PINNED) as lease:
        backend = lease.backend
    assert backend.threads and all(t.startswith("rt-gpu") for t in backend.threads)


async def test_manual_unload_and_pin():
    clock = Clock()
    m = _manager(clock)
    await m.load(MODEL_A, pin=True)
    clock.now += 120
    assert m.status().models[0]["pinned"]
    assert m._pick_victim() is None  # noqa: SLF001 - pinned runtime tidak dievict
    assert await m.unload("local/qwen-7b")
    assert not await m.unload("local/qwen-7b")


async def test_status_lists_models():
    m = _manager()
    await m.load(PINNED)
    st = m.status()
    assert (st.budget_mb, st.used_mb, st.free_mb) == (7200, 1300, 5900)
    assert st.models[0]["alias"] == "local/coder-1.5b" and st.models[0]["pinned"]
