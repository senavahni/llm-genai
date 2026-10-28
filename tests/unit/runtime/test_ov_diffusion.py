import asyncio
import base64
import hashlib
import io
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from app.utils.errors import (
    InvalidRequestError,
    ModelLoadFailed,
    RequestCancelled,
    UnsupportedParameter,
    UnsupportedSize,
)
from runtime.backends import ov_common, ov_diffusion_backend
from runtime.backends.ov_diffusion_backend import OVDiffusionBackend
from runtime.core.artifacts import sha256_artifact
from runtime.core.catalog import LocalModelSpec
from runtime.device.manager import DeviceManager
from tests.fakes import fake_genai


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(ov_diffusion_backend, "genai", fake_genai.module)
    fake_genai._ImagePipeline.step_delay_s = 0.0
    ov_common._verified.clear()
    return fake_genai


@pytest.fixture
def sd_spec(tmp_path):
    model = tmp_path / "sd15-int8"
    (model / "unet").mkdir(parents=True)
    (model / "unet" / "openvino_model.xml").write_text("unet")
    (model / "model_index.json").write_text("{}")

    def make(**config):
        cfg = {
            "device": "NPU",
            "component_devices": {"text_encoder": "NPU", "unet": "NPU", "vae": "NPU"},
            "allowed_sizes": ["512x512"],
            "default_steps": 4,
            "max_steps": 10,
            "guidance_scale": 7.5,
            "default_strength": 0.5,
            "cache_dir": str(tmp_path / "cache"),
            **config,
        }
        return LocalModelSpec(
            alias="local/sd-1.5",
            upstream_name="sd15",
            device="npu",
            runtime_backend="openvino_diffusion",
            model_type="image",
            artifact_path=str(model),
            artifact_sha256=sha256_artifact(model),
            vram_mb=3300,
            is_pinned=True,
            config=cfg,
        )

    return make


async def _loaded(spec) -> OVDiffusionBackend:
    backend = OVDiffusionBackend(spec)
    await backend.load()
    return backend


def _png(color=(200, 10, 10)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (64, 32), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def test_load_shares_models_and_reports_npu(fake, sd_spec):
    backend = await _loaded(sd_spec())
    i2i, t2i = fake._ImagePipeline.instances[-2:]
    assert t2i.source is i2i  # Text2ImagePipeline(i2i): model tidak dimuat dua kali
    assert i2i.shape == (1, 512, 512, 7.5)
    assert i2i.devices == ("NPU", "NPU", "NPU")
    assert backend.actual_device() == "npu" and backend.is_loaded()
    await backend.unload()
    assert not backend.is_loaded()


async def test_cpu_device_and_bad_sha_rejected(fake, sd_spec):
    with pytest.raises(ModelLoadFailed, match="GPU/NPU"):
        await _loaded(sd_spec(component_devices={"unet": "CPU"}))
    with pytest.raises(ModelLoadFailed, match="GPU/NPU"):
        await _loaded(sd_spec(device="AUTO", component_devices={}))
    with pytest.raises(ModelLoadFailed, match="sha256"):
        await _loaded(replace(sd_spec(), artifact_sha256="0" * 64))


async def test_gpu_unet_combination_reports_gpu(fake, sd_spec):
    backend = await _loaded(sd_spec(component_devices={"unet": "GPU"}))
    assert backend.actual_device() == "gpu"


async def test_text_to_image_deterministic_and_sequential_seeds(fake, sd_spec):
    backend = await _loaded(sd_spec())
    req = {"prompt": "kucing astronot", "n": 2, "seed": 42, "steps": 3}
    first = await backend.generate_images(req, asyncio.Event())
    second = await backend.generate_images(req, asyncio.Event())
    assert [r.seed for r in first] == [42, 43]
    assert [hashlib.sha256(r.png_bytes).hexdigest() for r in first] == [
        hashlib.sha256(r.png_bytes).hexdigest() for r in second
    ]
    assert first[0].png_bytes.startswith(b"\x89PNG") and first[0].steps == 3
    assert (first[0].width, first[0].height, first[0].guidance_scale) == (512, 512, 7.5)


async def test_image_to_image_uses_input_and_strength(fake, sd_spec):
    backend = await _loaded(sd_spec())
    [res] = await backend.generate_images(
        {"prompt": "malam hari", "image": "data:image/png;base64," + _png(), "seed": 1},
        asyncio.Event(),
    )
    call = fake._ImagePipeline.instances[-2].calls[-1]  # Image2ImagePipeline
    assert call["strength"] == 0.5 and call["image"].data.shape == (1, 512, 512, 3)
    assert res.png_bytes.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    ("req", "error"),
    [
        ({"prompt": ""}, InvalidRequestError),
        ({"prompt": "x", "size": "1024x1024"}, UnsupportedSize),
        ({"prompt": "x", "steps": 11}, InvalidRequestError),
        ({"prompt": "x", "n": 5}, InvalidRequestError),
        ({"prompt": "x", "guidance_scale": 5}, UnsupportedParameter),
        ({"prompt": "x", "image": _png(), "mask": _png()}, UnsupportedParameter),
        ({"prompt": "x", "image": "bukan-base64!"}, InvalidRequestError),
        ({"prompt": "x", "image": base64.b64encode(b"bukan gambar").decode()}, InvalidRequestError),
        ({"prompt": "x", "image": _png(), "strength": 1.5}, InvalidRequestError),
    ],
)
async def test_invalid_requests(fake, sd_spec, req, error):
    backend = await _loaded(sd_spec())
    with pytest.raises(error):
        await backend.generate_images(req, asyncio.Event())


async def test_long_prompt_warns_truncation(fake, sd_spec):
    backend = await _loaded(sd_spec())
    [res] = await backend.generate_images({"prompt": "kata " * 100}, asyncio.Event())
    assert res.warnings == ("prompt_truncated_to_77_clip_tokens",)


async def test_cancel_stops_within_one_step(fake, sd_spec):
    fake._ImagePipeline.step_delay_s = 0.05
    backend = await _loaded(sd_spec(max_steps=40))
    cancel = asyncio.Event()

    async def trigger():
        await asyncio.sleep(0.12)
        cancel.set()

    asyncio.ensure_future(trigger())
    with pytest.raises(RequestCancelled):
        await backend.generate_images({"prompt": "x", "steps": 40}, cancel)
    t2i = fake._ImagePipeline.instances[-1]
    assert t2i.steps_run <= 5  # berhenti ≤ 1 step setelah cancel, bukan 40


class _Events:
    def __init__(self):
        self.items = []

    def record(self, event, **kw):
        self.items.append((event, kw))


async def test_manager_records_compile_event_with_cache_hit(fake, sd_spec):
    spec = sd_spec()
    for expected_hit in (False, True):  # compile pertama mengisi cache, kedua memakai cache
        events = _Events()
        manager = DeviceManager("npu", 6200, backend_factory=OVDiffusionBackend, events=events)
        await manager.load(spec, "warmup", pin=True)
        compile_events = [kw for e, kw in events.items if e == "compile"]
        assert len(compile_events) == 1
        assert compile_events[0]["details"] == {"cache_hit": expected_hit}
        load = next(kw for e, kw in events.items if e == "load")
        assert load["details"]["actual_device"] == "npu"
        assert load["details"]["component_devices"] == {
            "text_encoder": "NPU",
            "unet": "NPU",
            "vae": "NPU",
        }
        await manager.unload_all("test")
        manager.close()


def test_png_roundtrip_of_fake_tensor():
    assert np.asarray(Image.open(io.BytesIO(base64.b64decode(_png())))).shape == (32, 64, 3)
