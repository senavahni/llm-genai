"""LGW-V1-02 dengan Qwen3-Embedding-0.6B nyata di GPU: kesetaraan vs referensi PyTorch dari spike
LGW-V1-01, dimensi 1024, token dari tokenizer, tidak pernah CPU.
Jalankan: `pytest --hardware tests/hardware/test_embed.py` (referensi: scripts/spike_embed.py)."""

import numpy as np
import pytest

from runtime.device.manager import DeviceManager
from scripts._embed_eval_set import QUERY_PREFIX, eval_set, query_set
from scripts.spike_embed import OUT as SPIKE_OUT
from tests.hardware.conftest import catalog_spec

pytestmark = pytest.mark.gpu
ALIAS = "local/qwen3-embedding-0.6b"


@pytest.fixture(scope="module")
async def gpu():
    manager = DeviceManager("gpu", 7000, queue_timeout_s=300, min_residency_s=0)
    yield manager
    await manager.unload_all("test")
    manager.close()


async def _embed(gpu, texts):
    spec = catalog_spec(ALIAS)
    async with gpu.acquire(spec) as lease:
        assert lease.device == "gpu"  # anti-CPU
        return await lease.backend.embed({"input": texts})


async def test_equivalence_with_pytorch_reference(gpu):
    ref_path = SPIKE_OUT / "ref.npy"
    if not ref_path.exists():
        pytest.skip("referensi belum ada: jalankan scripts/spike_embed.py")
    ref = np.load(ref_path)
    texts = [t for _, t in eval_set()] + [QUERY_PREFIX + q for q in query_set()]
    resp = await _embed(gpu, texts)
    vecs = np.array([d["embedding"] for d in resp["data"]], dtype=np.float32)
    assert vecs.shape == (len(texts), 1024)
    cos = (vecs * ref).sum(axis=1)
    assert cos.mean() >= 0.99 and cos.min() >= 0.98, (cos.mean(), cos.min())


async def test_usage_tokens_match_reference_tokenizer(gpu):
    import json

    ref_tokens = SPIKE_OUT / "ref_tokens.json"
    if not ref_tokens.exists():
        pytest.skip("referensi belum ada: jalankan scripts/spike_embed.py")
    texts = [t for _, t in eval_set()][:10]
    resp = await _embed(gpu, texts)
    assert resp["usage"]["prompt_tokens"] == sum(json.loads(ref_tokens.read_text())[:10])
