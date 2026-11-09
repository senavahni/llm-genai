"""LGW-V1-02: backend `openvino_embed` dengan `openvino_genai` palsu (tanpa hardware)."""

from dataclasses import replace

import numpy as np
import pytest

from app.utils.errors import (
    CapabilityNotSupported,
    ContextLengthExceeded,
    DeviceUnavailable,
    InvalidRequestError,
    ModelLoadFailed,
    UnsupportedParameter,
)
from runtime.backends import create_backend, ov_common, ov_embed_backend
from runtime.backends.ov_embed_backend import OVEmbedBackend
from runtime.core.artifacts import sha256_artifact
from runtime.core.catalog import LocalModelSpec
from runtime.device.manager import DeviceManager
from tests.fakes import fake_genai


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(ov_embed_backend, "genai", fake_genai.module)
    fake_genai.TextEmbeddingPipeline.instances.clear()
    ov_common._verified.clear()
    return fake_genai


@pytest.fixture
def embed_spec(tmp_path):
    model = tmp_path / "qwen3-embedding-0.6b-int8"
    model.mkdir()
    (model / "openvino_model.xml").write_text("ir")

    def make(**config):
        cfg = {"device": "GPU", "max_batch": 4, "cache_dir": str(tmp_path / "cache"), **config}
        return LocalModelSpec(
            alias="local/qwen3-embedding-0.6b",
            upstream_name="qwen3-embedding-0.6b",
            device="gpu",
            runtime_backend="openvino_embed",
            model_type="embedding",
            artifact_path=str(model),
            artifact_sha256=sha256_artifact(model),
            vram_mb=1200,
            is_pinned=True,
            config=cfg,
        )

    return make


async def _loaded(spec) -> OVEmbedBackend:
    backend = OVEmbedBackend(spec)
    await backend.load()
    return backend


def test_factory_creates_embed_backend(embed_spec):
    assert isinstance(create_backend(embed_spec()), OVEmbedBackend)


async def test_load_compiles_on_gpu_with_last_token_left_padding(fake, embed_spec):
    backend = OVEmbedBackend(embed_spec())
    result = await backend.load()
    pipe = fake.TextEmbeddingPipeline.instances[-1]
    assert pipe.device == "GPU"
    assert pipe.config.pooling_type == "LAST_TOKEN"
    assert pipe.config.normalize is True
    assert pipe.config.padding_side == "left"
    assert "CACHE_DIR" in pipe.props
    assert result.device == "gpu" and backend.actual_device() == "gpu"
    assert result.details["dimensions"] == fake.TextEmbeddingPipeline.dim
    assert "compile_ms" in result.details


async def test_cpu_device_rejected_without_fallback(fake, embed_spec):
    with pytest.raises(ModelLoadFailed, match="GPU/NPU"):
        await _loaded(embed_spec(device="CPU"))


async def test_sha256_mismatch_rejected(fake, embed_spec):
    bad = replace(embed_spec(), artifact_sha256="0" * 64)
    with pytest.raises(ModelLoadFailed, match="sha256"):
        await _loaded(bad)


async def test_embed_returns_ordered_vectors_and_tokenizer_usage(fake, embed_spec):
    backend = await _loaded(embed_spec(max_batch=2))
    texts = ["satu", "dua kata", "tiga kata ini", "empat kata di sini", "lima"]
    resp = await backend.embed({"model": "qwen3-embedding-0.6b", "input": texts})
    assert [d["index"] for d in resp["data"]] == [0, 1, 2, 3, 4]
    for item, text in zip(resp["data"], texts, strict=True):
        assert item["embedding"] == pytest.approx(fake.TextEmbeddingPipeline.vector(text))
        assert np.linalg.norm(item["embedding"]) == pytest.approx(1.0)
    # tokenizer palsu: jumlah kata + 2 token spesial
    expected = sum(len(t.split()) + 2 for t in texts)
    assert resp["usage"] == {"prompt_tokens": expected, "total_tokens": expected}
    pipe = fake.TextEmbeddingPipeline.instances[-1]
    assert pipe.batches[1:] == [2, 2, 1]  # batch[0] = warmup saat load
    assert resp["model"] == "qwen3-embedding-0.6b"


async def test_single_string_input(fake, embed_spec):
    backend = await _loaded(embed_spec())
    resp = await backend.embed({"input": "halo"})
    assert len(resp["data"]) == 1


@pytest.mark.parametrize(
    ("req", "error"),
    [
        ({"input": []}, InvalidRequestError),
        ({"input": [[1, 2, 3]]}, InvalidRequestError),
        ({"input": ["ok", ""]}, InvalidRequestError),
        ({"input": "x", "encoding_format": "base64"}, UnsupportedParameter),
        ({"input": "x", "dimensions": 256}, UnsupportedParameter),
    ],
)
async def test_invalid_requests(fake, embed_spec, req, error):
    backend = await _loaded(embed_spec())
    with pytest.raises(error):
        await backend.embed(req)


async def test_native_dimensions_accepted(fake, embed_spec):
    backend = await _loaded(embed_spec())
    resp = await backend.embed({"input": "x", "dimensions": fake.TextEmbeddingPipeline.dim})
    assert len(resp["data"][0]["embedding"]) == fake.TextEmbeddingPipeline.dim


async def test_input_too_long_reports_index(fake, embed_spec):
    backend = await _loaded(embed_spec(max_input_tokens=5))
    with pytest.raises(ContextLengthExceeded, match=r"\[1\]"):
        await backend.embed({"input": ["pendek", "ini teks yang terlalu panjang sekali"]})


def test_unknown_pooling_rejected(embed_spec):
    with pytest.raises(ModelLoadFailed, match="pooling"):
        OVEmbedBackend(embed_spec(pooling="max"))


async def test_unload(fake, embed_spec):
    backend = await _loaded(embed_spec())
    await backend.unload()
    assert not backend.is_loaded()


async def test_other_backends_do_not_embed(embed_spec):
    from tests.fakes.fake_backend import FakeBackend

    with pytest.raises(CapabilityNotSupported):
        await FakeBackend(embed_spec()).embed({"input": "x"})


async def test_device_manager_pins_embed_model_and_rejects_cpu(fake, embed_spec, monkeypatch):
    mgr = DeviceManager("gpu", 7000, min_residency_s=0)
    try:
        spec = embed_spec()
        async with mgr.acquire(spec) as lease:
            assert lease.device == "gpu"
            resp = await lease.backend.embed({"input": ["a", "b"]})
        assert len(resp["data"]) == 2
        assert mgr.status().models[0]["pinned"] is True
    finally:
        await mgr.unload_all("test")
        mgr.close()

    # backend yang ternyata jalan di CPU ditolak DeviceManager
    monkeypatch.setattr(OVEmbedBackend, "actual_device", lambda self: "cpu")
    mgr = DeviceManager("gpu", 7000, min_residency_s=0)
    try:
        with pytest.raises(DeviceUnavailable):
            async with mgr.acquire(embed_spec()):
                pass
    finally:
        mgr.close()
