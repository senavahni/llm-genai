import shutil

import pytest

from runtime.core.artifacts import sha256_artifact
from scripts._seedfile import SEED_FILE, load_seed, local_models, patch_model_value
from scripts.measure_models import pipeline_properties, round_vram, validate_budget

SAMPLE_SEED = """\
# komentar kepala
models:
  # ===== lokal =====
  - alias: local/a
    device: gpu
    vram_mb: 1000  # perkiraan
    config: {n_ctx: 4096,
             replicas: 1}

  - alias: local/b
    device: npu
    vram_mb: 2000
  # ===== remote =====
  - {alias: remote/x, provider: openai}
routes: []
"""


@pytest.fixture
def seed_copy(tmp_path):
    path = tmp_path / "seed.yaml"
    path.write_text(SAMPLE_SEED, encoding="utf-8")
    return path


def test_patch_replaces_and_inserts_without_touching_others(seed_copy):
    before = seed_copy.read_text(encoding="utf-8")
    assert patch_model_value("local/a", "vram_mb", 1234, seed_copy)
    assert patch_model_value("local/a", "artifact_sha256", "a" * 64, seed_copy)
    assert not patch_model_value("local/missing", "vram_mb", 1, seed_copy)
    data = load_seed(seed_copy)
    a = next(x for x in data["models"] if x["alias"] == "local/a")
    assert a["vram_mb"] == 1234 and a["artifact_sha256"] == "a" * 64
    assert a["config"] == {"n_ctx": 4096, "replicas": 1}
    b = next(x for x in data["models"] if x["alias"] == "local/b")
    assert b["vram_mb"] == 2000 and "artifact_sha256" not in b
    after = seed_copy.read_text(encoding="utf-8")
    assert after.count("#") == before.count("#") - 1  # hanya komentar inline baris vram_mb
    assert len(after.splitlines()) == len(before.splitlines()) + 1
    # key baru disisipkan tepat setelah vram_mb
    lines = after.splitlines()
    assert lines[lines.index("    vram_mb: 1234") + 1] == "    artifact_sha256: " + "a" * 64


def test_real_seed_file_is_patchable(tmp_path):
    path = tmp_path / "seed.yaml"
    shutil.copy(SEED_FILE, path)
    assert patch_model_value("local/sd-1.5", "vram_mb", 2600, path)
    assert (
        next(m for m in load_seed(path)["models"] if m["alias"] == "local/sd-1.5")["vram_mb"]
        == 2600
    )


def test_catalog_is_qwen_and_sd_on_openvino_gpu_npu():
    models = local_models(load_seed())
    assert sorted(m["alias"] for m in models) == [
        "local/qwen2-vl-2b",
        "local/qwen2.5-7b",
        "local/qwen2.5-coder-1.5b",
        "local/qwen2.5-coder-7b",
        "local/sd-1.5",
    ]
    for m in models:
        assert m["provider"] == "openvino"
        assert m["runtime_backend"] in ("openvino_llm", "openvino_vlm", "openvino_diffusion")
        assert m["device"] in ("gpu", "npu")
        devices = [m["config"]["device"], *(m["config"].get("component_devices") or {}).values()]
        assert all(d == m["device"].upper() or d in ("GPU", "NPU") for d in devices)
        assert "CPU" not in devices and "AUTO" not in devices


def test_routes_only_reference_catalog_models():
    data = load_seed()
    aliases = {m["alias"] for m in data["models"]}
    for route in data["routes"]:
        for target in route["targets"]:
            assert target["model"] in aliases, (route["alias"], target["model"])


def test_npu_pipeline_properties():
    m = {"config": {"device": "NPU", "max_prompt_len": 2048, "min_response_len": 256}}
    props = pipeline_properties(m, "NPU")
    assert props["MAX_PROMPT_LEN"] == 2048 and props["MIN_RESPONSE_LEN"] == 256
    assert props["CACHE_DIR"].endswith("ov_cache")
    assert "MAX_PROMPT_LEN" not in pipeline_properties(m, "GPU")


def test_sha256_artifact_dir_detects_changes(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "openvino_model.xml").write_text("a")
    (tmp_path / "sub" / "w.bin").write_bytes(b"1")
    (tmp_path / "README.md").write_text("abaikan")
    first = sha256_artifact(tmp_path)
    (tmp_path / "README.md").write_text("berubah")
    assert sha256_artifact(tmp_path) == first
    (tmp_path / "sub" / "w.bin").write_bytes(b"2")
    assert sha256_artifact(tmp_path) != first
    assert sha256_artifact(tmp_path / "openvino_model.xml") == sha256_artifact(
        tmp_path / "openvino_model.xml"
    )


def test_round_vram():
    assert round_vram(1000) == 1100  # +5% → 1050 → kelipatan 100 ke atas
    assert round_vram(1238) == 1300
    assert round_vram(-5) == 0


def test_validate_budget_report():
    models = local_models(load_seed())
    gpu = [m for m in models if m["device"] == "gpu"]
    pinned = sum(m["vram_mb"] for m in gpu if m["is_pinned"])
    swap = max(m["vram_mb"] for m in gpu if not m["is_pinned"])
    npu = sum(m["vram_mb"] for m in models if m["device"] == "npu" and m["is_pinned"])
    report = validate_budget(models, {})
    assert report[0].startswith(f"GPU: pinned {pinned} + swap terbesar {swap}")
    assert report[1].startswith(f"NPU: pinned {npu} + swap terbesar")
