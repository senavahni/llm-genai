"""Uji kompilasi & inferensi NPU (standalone, sebelum runtime). Hasil → logs/npu_test.json.

    "%PY%" scripts\\test_npu.py                       :: SD fp16 + bge-m3
    "%PY%" scripts\\test_npu.py --sd sd15-int8 --steps 20


Compile pertama mengisi OV_CACHE_DIR; jalankan dua kali untuk melihat efek cache (≥ 5× lebih
cepat). Tidak pernah memakai device CPU/AUTO."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OV_DIR = ROOT / "local_models" / "openvino"
CACHE_DIR = os.environ.get("OV_CACHE_DIR") or str(ROOT / "local_models" / "ov_cache")


def _rss_mb() -> int:
    import psutil

    return int(psutil.Process().memory_info().rss / 1024 / 1024)


def test_sd(path: Path, steps: int, device: str, out_png: Path) -> dict[str, Any]:
    from optimum.intel import OVStableDiffusionPipeline

    res: dict[str, Any] = {"model": str(path), "device": device, "rss_before_mb": _rss_mb()}
    t = time.perf_counter()
    pipe = OVStableDiffusionPipeline.from_pretrained(
        path, compile=False, ov_config={"CACHE_DIR": CACHE_DIR}
    )
    pipe.reshape(batch_size=1, height=512, width=512, num_images_per_prompt=1)
    pipe.to(device)
    pipe.compile()
    res["compile_s"] = round(time.perf_counter() - t, 2)
    res["rss_after_compile_mb"] = _rss_mb()
    t = time.perf_counter()
    image = pipe(
        "an astronaut cat, watercolor", num_inference_steps=steps, guidance_scale=7.5
    ).images[0]
    res["generate_s"] = round(time.perf_counter() - t, 2)
    image.save(out_png)
    res["output"] = str(out_png)
    return res


def test_bge(path: Path, device: str) -> dict[str, Any]:
    from optimum.intel import OVModelForFeatureExtraction
    from transformers import AutoTokenizer

    res: dict[str, Any] = {"model": str(path), "device": device, "rss_before_mb": _rss_mb()}
    t = time.perf_counter()
    model = OVModelForFeatureExtraction.from_pretrained(
        path, device=device, compile=False, ov_config={"CACHE_DIR": CACHE_DIR}
    )
    model.reshape(8, 512)
    model.compile()
    res["compile_s"] = round(time.perf_counter() - t, 2)
    tok = AutoTokenizer.from_pretrained(path)
    sentences = [f"Kalimat uji nomor {i} tentang cuaca di Bandung." for i in range(8)]
    batch = tok(
        sentences, padding="max_length", max_length=512, truncation=True, return_tensors="np"
    )
    t = time.perf_counter()
    out = model(**batch)
    res["encode_8_s"] = round(time.perf_counter() - t, 3)
    res["dim"] = int(out.last_hidden_state.shape[-1])
    res["rss_after_mb"] = _rss_mb()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sd", default="sd15-fp16")
    ap.add_argument("--bge", default="bge-m3-int8")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--device", default="NPU", choices=["NPU", "GPU"])

    ap.add_argument("--skip-sd", action="store_true")
    ap.add_argument("--skip-bge", action="store_true")
    args = ap.parse_args()

    results: dict[str, Any] = {"cache_dir": CACHE_DIR}
    if not args.skip_sd:
        try:
            results["sd"] = test_sd(
                OV_DIR / args.sd, args.steps, args.device, ROOT / "logs" / "npu_test_sd.png"
            )
        except Exception as exc:  # noqa: BLE001 - catat lalu lanjut ke bge
            results["sd"] = {"error": f"{type(exc).__name__}: {exc}"}
    if not args.skip_bge:
        try:
            results["bge"] = test_bge(OV_DIR / args.bge, args.device)
        except Exception as exc:  # noqa: BLE001
            results["bge"] = {"error": f"{type(exc).__name__}: {exc}"}
    out = ROOT / "logs" / "npu_test.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 1 if any("error" in v for v in results.values() if isinstance(v, dict)) else 0


if __name__ == "__main__":
    sys.exit(main())
