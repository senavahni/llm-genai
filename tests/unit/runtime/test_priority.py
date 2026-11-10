"""LGW-V1-04: antrean prioritas runtime — interactive menyela di antara batch bulk, konkurensi
bulk dibatasi, urutan output tetap."""

import asyncio
import time

import numpy as np
import pytest

from app.utils.errors import InvalidRequestError, ModelBusy, RequestCancelled
from runtime.backends import ov_common, ov_embed_backend
from runtime.backends.ov_embed_backend import OVEmbedBackend
from runtime.core.catalog import LocalModelSpec, RuntimeCatalog
from runtime.device.manager import DeviceManager
from runtime.device.priority import BULK, INTERACTIVE, PrioritySemaphore
from runtime.services.inference_service import InferenceService
from tests.fakes import fake_genai


# ------------------------------------------------------------- semaphore
async def test_release_goes_to_highest_priority_then_fifo():
    sem = PrioritySemaphore(1)
    await sem.acquire()
    order: list[str] = []

    async def wait(name: str, prio: int) -> None:
        await sem.acquire(prio)
        order.append(name)
        sem.release()

    tasks = [asyncio.create_task(wait("bulk-1", BULK)), asyncio.create_task(wait("bulk-2", BULK))]
    await asyncio.sleep(0)
    tasks.append(asyncio.create_task(wait("interactive", INTERACTIVE)))
    await asyncio.sleep(0)
    assert sem.waiting(BULK) == 2 and sem.waiting(INTERACTIVE) == 1
    sem.release()
    await asyncio.gather(*tasks)
    assert order == ["interactive", "bulk-1", "bulk-2"]
    assert sem._value == 1  # noqa: SLF001


async def test_cancelled_waiter_does_not_leak_slot():
    sem = PrioritySemaphore(1)
    await sem.acquire()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(sem.acquire(BULK), timeout=0.01)
    sem.release()
    await asyncio.wait_for(sem.acquire(), timeout=0.1)  # slot kembali, tidak hilang
    assert not sem.waiting()


# --------------------------------------------------------- inference service
@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(ov_embed_backend, "genai", fake_genai.module)
    monkeypatch.setattr(fake_genai.TextEmbeddingPipeline, "batch_delay_s", 0.05)
    ov_common._verified.clear()
    model = tmp_path / "ir"
    model.mkdir()
    (model / "openvino_model.xml").write_text("ir")
    spec = LocalModelSpec(
        alias="local/qwen3-embedding-0.6b",
        upstream_name="qwen3-embedding-0.6b",
        device="gpu",
        runtime_backend="openvino_embed",
        model_type="embedding",
        artifact_path=str(model),
        vram_mb=1800,
        is_pinned=True,
        config={"device": "GPU", "max_batch": 2, "cache_dir": str(tmp_path / "cache")},
    )
    catalog = RuntimeCatalog(session_factory=None)  # type: ignore[arg-type]
    catalog.set({spec.upstream_name: spec})
    manager = DeviceManager(
        "gpu", 5000, queue_timeout_s=10, min_residency_s=0, backend_factory=OVEmbedBackend
    )

    def make(**kw) -> InferenceService:
        return InferenceService(catalog, {"gpu": manager}, **kw)

    yield make
    manager.close()


def _body(n: int, priority: str, prefix: str = "t") -> dict:
    return {
        "model": "qwen3-embedding-0.6b",
        "input": [f"{prefix}{i}" for i in range(n)],
        "priority": priority,
    }


async def test_interactive_overtakes_running_bulk(service):
    svc = service()
    await svc.embeddings(_body(1, "interactive"), None)  # load + warmup di luar pengukuran
    done: dict[str, float] = {}

    async def run(name: str, body: dict) -> dict:
        result = await svc.embeddings(body, None)
        done[name] = time.perf_counter()
        return result

    bulk = asyncio.create_task(run("bulk", _body(20, "bulk")))  # 10 batch × 50 ms
    await asyncio.sleep(0.12)  # bulk sedang berjalan (batch ke-2/3)
    start = time.perf_counter()
    inter = await run("interactive", _body(2, "interactive", "q"))
    latency = time.perf_counter() - start
    bulk_resp = await bulk
    assert done["interactive"] < done["bulk"]
    assert latency < 0.25  # ≤ ±1 batch bulk berjalan + 1 batch sendiri, bukan sisa 8 batch
    assert inter["x_runtime"]["priority"] == "interactive"
    assert bulk_resp["x_runtime"] == {
        **bulk_resp["x_runtime"],
        "priority": "bulk",
        "batches": 10,
        "device": "gpu",
    }
    # urutan output bulk tetap
    expected = [fake_genai.TextEmbeddingPipeline.vector(f"t{i}") for i in range(20)]
    assert np.allclose([d["embedding"] for d in bulk_resp["data"]], expected)


async def test_bulk_concurrency_limited(service):
    svc = service(bulk_concurrency=1, bulk_queue_timeout_s=0.05)
    first = asyncio.create_task(svc.embeddings(_body(10, "bulk"), None))
    await asyncio.sleep(0.02)
    with pytest.raises(ModelBusy, match="antrean bulk"):
        await svc.embeddings(_body(1, "bulk"), None)
    await first
    await svc.embeddings(_body(1, "bulk"), None)  # gate dilepas setelah selesai


async def test_invalid_priority_and_cancel(service):
    svc = service()
    with pytest.raises(InvalidRequestError, match="priority"):
        await svc.embeddings(_body(1, "urgent"), None)
    cancel = asyncio.Event()
    cancel.set()
    with pytest.raises(RequestCancelled):
        await svc.embeddings(_body(4, "bulk"), None, cancel)
