"""Uji Stable Diffusion v1.5 lewat OpenVINO GenAI (standalone, sebelum runtime): text-to-image dan
image-to-image, device per komponen, cache compile, determinisme seed. Hasil → logs/sd_test.json
dan gambar logs/sd_t2i.png, logs/sd_i2i.png.

    scripts\\conda-run.bat python scripts\\test_sd.py                         :: INT8, semua NPU
    scripts\\conda-run.bat python scripts\\test_sd.py --devices NPU,GPU,NPU   :: UNet di GPU
    scripts\\conda-run.bat python scripts\\test_sd.py --model sd15-fp16 --steps 25

Urutan --devices: text_encoder, unet (denoise), vae. Device CPU/AUTO tidak diterima. Compile
pertama mengisi CACHE_DIR; jalankan dua kali untuk melihat efek cache."""

import argparse
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.measure_models import DeviceMemory, PeakSampler  # noqa: E402

OV_DIR = ROOT / "local_models" / "openvino"
CACHE_DIR = ROOT / "local_models" / "ov_cache"
DEVICES = ("GPU", "NPU")
PROMPT = "an astronaut cat sitting on the moon, watercolor painting"
I2I_PROMPT = "the same scene at night, oil painting, dramatic lighting"


def _png(tensor: Any) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(tensor.data[0]).save(buf, format="PNG")
    return buf.getvalue()


def _to_tensor(png: bytes) -> Any:
    import numpy as np
    import openvino as ov
    from PIL import Image

    img = Image.open(io.BytesIO(png)).convert("RGB").resize((512, 512))
    return ov.Tensor(np.asarray(img, dtype=np.uint8)[None])


def run(
    model: Path, devices: list[str], steps: int, seed: int, guidance: float, strength: float
) -> dict[str, Any]:
    import openvino_genai as ov_genai
    import psutil

    mem, proc = DeviceMemory(), psutil.Process()
    before, before_rss = mem.read(), mem.rss()
    sampler = PeakSampler(mem)
    sampler.start()
    res: dict[str, Any] = {"model": model.name, "devices": devices, "steps": steps, "seed": seed}
    try:
        # satu set model untuk dua mode: Image2ImagePipeline (butuh VAE encoder) dikompilasi,
        # Text2ImagePipeline dibuat darinya sehingga UNet/text encoder/VAE tidak dimuat dua kali
        t = time.perf_counter()
        i2i = ov_genai.Image2ImagePipeline(str(model))
        i2i.reshape(1, 512, 512, guidance)
        i2i.compile(*devices, CACHE_DIR=str(CACHE_DIR))
        t2i = ov_genai.Text2ImagePipeline(i2i)
        res["compile_s"] = round(time.perf_counter() - t, 2)

        def generate(pipe: Any, *args: Any, **kw: Any) -> tuple[bytes, float, float]:
            cpu0, t0 = proc.cpu_times(), time.perf_counter()
            image = pipe.generate(
                *args,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=ov_genai.CppStdGenerator(seed),
                **kw,
            )
            wall = time.perf_counter() - t0
            cpu1 = proc.cpu_times()
            cpu_s = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
            return _png(image), round(wall, 2), round(cpu_s / max(wall, 1e-6), 2)

        png1, res["t2i_generate_s"], res["t2i_cpu_ratio"] = generate(t2i, PROMPT)
        png2, res["t2i_generate_2_s"], _ = generate(t2i, PROMPT)
        res["t2i_deterministic"] = hashlib.sha256(png1).digest() == hashlib.sha256(png2).digest()
        (ROOT / "logs" / "sd_t2i.png").write_bytes(png1)

        png3, res["i2i_generate_s"], res["i2i_cpu_ratio"] = generate(
            i2i, I2I_PROMPT, _to_tensor(png1), strength=strength
        )
        (ROOT / "logs" / "sd_i2i.png").write_bytes(png3)
    except Exception as exc:  # noqa: BLE001 - catat ke json
        res["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        peak, peak_rss = sampler.stop()
    res.update(
        memory_method=mem.method,
        device_mem_delta_mb=peak - before,
        rss_delta_mb=peak_rss - before_rss,
        cpu_count=psutil.cpu_count(),
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sd15-int8")
    ap.add_argument("--devices", default="NPU,NPU,NPU", help="text_encoder,unet,vae")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--guidance", type=float, default=7.5)
    ap.add_argument("--strength", type=float, default=0.6)
    args = ap.parse_args()
    devices = [d.strip().upper() for d in args.devices.split(",")]
    if len(devices) != 3 or any(d not in DEVICES for d in devices):
        ap.error("--devices harus 3 nilai dari GPU/NPU (CPU/AUTO ditolak)")

    res = run(OV_DIR / args.model, devices, args.steps, args.seed, args.guidance, args.strength)
    out = ROOT / "logs" / "sd_test.json"
    history = json.loads(out.read_text()) if out.exists() else []
    history.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), **res})
    out.write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))
    return 1 if "error" in res else 0


if __name__ == "__main__":
    sys.exit(main())
