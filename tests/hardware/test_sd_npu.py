"""TASK-12 di NPU nyata: t2i deterministik, i2i, cancel, event compile + cache."""

import asyncio
import base64
import hashlib
import io
import time

import pytest
from PIL import Image

from app.utils.errors import RequestCancelled
from runtime.backends.ov_diffusion_backend import OVDiffusionBackend
from runtime.device.manager import DeviceManager

pytestmark = pytest.mark.npu


class _Events:
    def __init__(self):
        self.items = []

    def record(self, event, **kw):
        self.items.append((event, kw))


@pytest.fixture(scope="module")
async def sd():
    from tests.hardware.conftest import catalog_spec

    spec = catalog_spec("local/sd-1.5")
    events = _Events()
    manager = DeviceManager("npu", 6200, backend_factory=OVDiffusionBackend, events=events)
    await manager.load(spec, "test", pin=True)
    yield manager, spec, events
    await manager.unload_all("test")
    manager.close()


async def _generate(manager, spec, req, cancel=None):
    async with manager.acquire(spec) as lease:
        assert lease.device == "npu"
        return await lease.backend.generate_images(req, cancel or asyncio.Event())


async def test_compile_event_and_devices(sd):
    _, _, events = sd
    compile_kw = next(kw for e, kw in events.items if e == "compile")
    load_kw = next(kw for e, kw in events.items if e == "load")
    assert load_kw["details"]["component_devices"] == {
        "text_encoder": "NPU",
        "unet": "NPU",
        "vae": "NPU",
    }
    # cache sudah dihangatkan TASK-09 → compile dari cache (detik, bukan menit)
    assert compile_kw["details"]["cache_hit"] is True
    assert compile_kw["duration_ms"] < 30_000


async def test_text_to_image_deterministic_25_steps(sd):
    manager, spec, _ = sd
    req = {"prompt": "a red bicycle in front of a blue house", "seed": 7, "steps": 25}
    first = await _generate(manager, spec, req)
    second = await _generate(manager, spec, req)
    digest = [hashlib.sha256(r[0].png_bytes).hexdigest() for r in (first, second)]
    assert digest[0] == digest[1]
    assert Image.open(io.BytesIO(first[0].png_bytes)).size == (512, 512)


async def test_image_to_image(sd):
    manager, spec, _ = sd
    [base] = await _generate(manager, spec, {"prompt": "a lighthouse on a cliff", "seed": 3})
    [edited] = await _generate(
        manager,
        spec,
        {
            "prompt": "a lighthouse on a cliff at night, oil painting",
            "image": base64.b64encode(base.png_bytes).decode(),
            "strength": 0.5,
            "seed": 3,
        },
    )
    assert edited.png_bytes != base.png_bytes
    assert Image.open(io.BytesIO(edited.png_bytes)).size == (512, 512)


async def test_cancel_within_one_step(sd):
    manager, spec, _ = sd
    cancel = asyncio.Event()
    started = time.perf_counter()

    async def trigger():
        await asyncio.sleep(3)
        cancel.set()

    asyncio.ensure_future(trigger())
    with pytest.raises(RequestCancelled):
        await _generate(manager, spec, {"prompt": "a forest", "steps": 50}, cancel)
    elapsed = time.perf_counter() - started
    # 50 step ±50 s; berhenti ≤ 1 step (±1 s) setelah cancel di detik ke-3
    assert elapsed < 6, elapsed
