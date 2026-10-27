import shutil

import pytest

from scripts._seedfile import SEED_FILE, load_seed, local_models, patch_model_value
from scripts.download_models import resolve_files
from scripts.measure_models import round_vram, validate_budget


@pytest.fixture
def seed_copy(tmp_path):
    path = tmp_path / "seed.yaml"
    shutil.copy(SEED_FILE, path)
    return path


def test_patch_replaces_and_inserts_without_touching_others(seed_copy):
    before = seed_copy.read_text(encoding="utf-8")
    assert patch_model_value("local/qwen2.5-7b", "vram_mb", 5123, seed_copy)
    assert patch_model_value("local/qwen2.5-7b", "artifact_sha256", "a" * 64, seed_copy)
    assert not patch_model_value("local/missing", "vram_mb", 1, seed_copy)
    data = load_seed(seed_copy)
    m = next(x for x in data["models"] if x["alias"] == "local/qwen2.5-7b")
    assert m["vram_mb"] == 5123 and m["artifact_sha256"] == "a" * 64
    other = next(x for x in data["models"] if x["alias"] == "local/sd-1.5")
    assert other["vram_mb"] == 2500 and "artifact_sha256" not in other
    after = seed_copy.read_text(encoding="utf-8")
    assert after.count("#") == before.count("#")  # komentar utuh
    assert len(after.splitlines()) == len(before.splitlines()) + 1


def test_catalog_has_11_local_models():
    assert len(local_models(load_seed())) == 11


def test_resolve_files_patterns_and_shards():
    siblings = {
        "a-Q4_K_M.gguf": 1,
        "a-Q8_0.gguf": 2,
        "b-q4_k_m-00001-of-00002.gguf": 3,
        "b-q4_k_m-00002-of-00002.gguf": 4,
    }
    assert resolve_files("r", "*q4_k_m.gguf", siblings) == ["a-Q4_K_M.gguf"]
    assert resolve_files("r", "b-q4_k_m-00001-of-*.gguf", siblings) == [
        "b-q4_k_m-00001-of-00002.gguf",
        "b-q4_k_m-00002-of-00002.gguf",
    ]
    with pytest.raises(SystemExit):
        resolve_files("r", "*.bin", siblings)


def test_round_vram():
    assert round_vram(1000) == 1100  # +5% → 1050 → kelipatan 100 ke atas
    assert round_vram(1238) == 1300
    assert round_vram(-5) == 0


def test_validate_budget_report():
    models = local_models(load_seed())
    pinned = sum(m["vram_mb"] for m in models if m["device"] == "gpu" and m["is_pinned"])
    report = validate_budget(models, {})
    assert report[0].startswith(f"GPU: pinned {pinned} + swap terbesar 5800")
    assert "NPU: pinned 3200 MB" in report[1]
