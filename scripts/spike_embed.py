"""Spike LGW-V1-01: Qwen3-Embedding-0.6B di OpenVINO GPU — kesetaraan vs referensi HF/PyTorch,
waktu compile, ukuran cache, memori puncak, throughput kasar.

    scripts\\conda-run.bat python scripts\\convert_openvino.py ^
        --only qwen3-embedding-0.6b-fp16,qwen3-embedding-0.6b-int8
    scripts\\conda-run.bat python scripts\\spike_embed.py            :: referensi + semua varian
    scripts\\conda-run.bat python scripts\\spike_embed.py --variant genai-int8

Referensi = transformers (torch CPU, FP32), HANYA sebagai pembanding kesetaraan, bukan jalur
inferensi. Setiap varian dijalankan di subproses sendiri agar angka memori tidak tercampur.
Hasil: local_models/spike/qwen3-embedding/*.json (+ ref.npy)."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._embed_eval_set import QUERY_PREFIX, eval_set, query_set  # noqa: E402

SRC = ROOT / "local_models" / "hf_src" / "qwen3-embedding-0.6b"
IR = {p: ROOT / "local_models" / "openvino" / f"qwen3-embedding-0.6b-{p}" for p in ("fp16", "int8")}
OUT = ROOT / "local_models" / "spike" / "qwen3-embedding"
VARIANTS = ("genai-fp16", "genai-int8", "optimum-fp16", "optimum-int8")
MAX_LENGTH = 8192
REF_BATCH = 4


def texts() -> list[str]:
    """Dokumen (100, tanpa prefix) + query (20, dengan prefix instruksi)."""
    return [t for _, t in eval_set()] + [QUERY_PREFIX + q for q in query_set()]


def categories() -> list[str]:
    return [c for c, _ in eval_set()] + ["query"] * len(query_set())


def l2(vecs: Any) -> Any:
    import numpy as np

    arr = np.asarray(vecs, dtype=np.float32)
    return arr / np.linalg.norm(arr, axis=1, keepdims=True)


# --------------------------------------------------------------------- referensi
def run_reference() -> None:
    import numpy as np
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(SRC, padding_side="left")
    model = AutoModel.from_pretrained(SRC, torch_dtype=torch.float32).eval()
    items = texts()
    out, lengths = [], []
    with torch.inference_mode():
        for i in range(0, len(items), REF_BATCH):
            batch = tok(
                items[i : i + REF_BATCH],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
            )
            lengths += batch["attention_mask"].sum(dim=1).tolist()
            hidden = model(**batch).last_hidden_state
            out.append(hidden[:, -1].float().numpy())  # left padding → token terakhir
    OUT.mkdir(parents=True, exist_ok=True)
    np.save(OUT / "ref.npy", l2(np.concatenate(out)))
    (OUT / "ref_tokens.json").write_text(json.dumps(lengths))
    print(f"referensi: {len(items)} vektor, token min/max {min(lengths)}/{max(lengths)}")


# ----------------------------------------------------------------------- varian
def _mem() -> dict[str, int]:
    import psutil

    info = psutil.Process().memory_info()
    mb = 1024 * 1024
    return {
        "private_mb": int(getattr(info, "private", info.vms) // mb),
        "peak_commit_mb": int(getattr(info, "peak_pagefile", info.vms) // mb),
        "peak_wset_mb": int(getattr(info, "peak_wset", info.rss) // mb),
    }


def _dir_mb(path: Path) -> float:
    return round(sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1e6, 1)


class GenAIEmbedder:
    def __init__(self, ir: Path, cache: Path) -> None:
        import openvino_genai as g

        cfg = g.TextEmbeddingPipeline.Config()
        cfg.pooling_type = g.TextEmbeddingPipeline.PoolingType.LAST_TOKEN
        cfg.normalize = True
        cfg.padding_side = "left"
        cfg.max_length = MAX_LENGTH
        self.pipe = g.TextEmbeddingPipeline(str(ir), "GPU", cfg, CACHE_DIR=str(cache))

    def embed(self, batch: list[str]) -> Any:
        return l2(self.pipe.embed_documents(batch))


class OptimumEmbedder:
    def __init__(self, ir: Path, cache: Path) -> None:
        from optimum.intel import OVModelForFeatureExtraction
        from transformers import AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(ir, padding_side="left")
        self.model = OVModelForFeatureExtraction.from_pretrained(
            ir, device="GPU", ov_config={"CACHE_DIR": str(cache)}, compile=True
        )

    def embed(self, batch: list[str]) -> Any:
        enc = self.tok(
            batch, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="np"
        )
        hidden = self.model(**enc).last_hidden_state
        return l2(hidden[:, -1])


def _make(variant: str, cache: Path) -> Any:
    path, prec = variant.split("-")
    cls = GenAIEmbedder if path == "genai" else OptimumEmbedder
    return cls(IR[prec], cache)


def _throughput(emb: Any, pool: list[str], batch: int, n: int) -> float:
    items = (pool * (n // len(pool) + 1))[:n]
    emb.embed(items[:batch])  # pemanasan shape
    start = time.perf_counter()
    for i in range(0, n, batch):
        emb.embed(items[i : i + batch])
    return round(n / (time.perf_counter() - start), 1)


def run_variant(variant: str) -> dict[str, Any]:
    import gc

    import numpy as np

    ref = np.load(OUT / "ref.npy")
    cache = ROOT / "local_models" / "ov_cache" / f"spike-{variant}"
    shutil.rmtree(cache, ignore_errors=True)
    cache.mkdir(parents=True)
    base = _mem()

    start = time.perf_counter()
    emb = _make(variant, cache)
    cold_ms = int((time.perf_counter() - start) * 1000)
    after_load = _mem()
    del emb
    gc.collect()
    start = time.perf_counter()
    emb = _make(variant, cache)
    warm_ms = int((time.perf_counter() - start) * 1000)

    items = texts()
    vecs = np.concatenate([emb.embed(items[i : i + 8]) for i in range(0, len(items), 8)])
    cos = (vecs * ref).sum(axis=1)
    cats = categories()
    per_cat = {
        c: round(float(min(cos[i] for i in range(len(cats)) if cats[i] == c)), 5)
        for c in dict.fromkeys(cats)
    }
    short = [t for c, t in eval_set() if c != "long"]
    long_ = [t for c, t in eval_set() if c == "long"]
    result = {
        "variant": variant,
        "dim": int(vecs.shape[1]),
        "cos_mean": round(float(cos.mean()), 5),
        "cos_min": round(float(cos.min()), 5),
        "cos_min_per_category": per_cat,
        "compile_cold_ms": cold_ms,
        "compile_warm_ms": warm_ms,
        "cache_mb": _dir_mb(cache),
        "ir_mb": _dir_mb(IR[variant.split("-")[1]]),
        "mem_base": base,
        "mem_after_load": after_load,
        "throughput_short_docs_per_s": {
            "b8": _throughput(emb, short, 8, 128),
            "b32": _throughput(emb, short, 32, 128),
        },
        "throughput_long_docs_per_s": {"b8": _throughput(emb, long_, 8, 32)},
        "mem_peak": _mem(),
    }
    result["mem_peak_delta_commit_mb"] = result["mem_peak"]["peak_commit_mb"] - base["private_mb"]
    result["passed"] = result["cos_mean"] >= 0.99 and result["cos_min"] >= 0.98
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{variant}.json").write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=VARIANTS)
    ap.add_argument("--skip-ref", action="store_true")
    args = ap.parse_args()
    if args.variant:
        print(json.dumps(run_variant(args.variant), indent=2))
        return 0
    if not args.skip_ref or not (OUT / "ref.npy").exists():
        run_reference()
    failed = []
    for v in VARIANTS:
        print(f"=== {v}", flush=True)
        code = subprocess.run([sys.executable, __file__, "--variant", v], check=False).returncode
        if code:
            failed.append(v)
    print("gagal:", failed or "-")
    return 1 if len(failed) == len(VARIANTS) else 0


if __name__ == "__main__":
    sys.exit(main())
