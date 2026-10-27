"""Ukur memori perangkat & performa tiap model GGUF, SATU PER SATU, lalu validasi budget §7.5.

    "%PY%" scripts\\measure_models.py --only qwen2.5-coder-1.5b
    "%PY%" scripts\\measure_models.py --update-yaml       :: tulis vram_mb ke seed_models.yaml
    "%PY%" scripts\\measure_models.py --validate-only     :: hanya cek budget dari nilai yaml
    lalu: "%PY%" scripts\\manage.py seed --update-local

Memori perangkat:
- NVIDIA: pynvml (nvmlDeviceGetMemoryInfo).
- Intel/AMD (Vulkan, termasuk iGPU UMA): performance counter Windows
  `\\GPU Process Memory(pid_<PID>*)\\Dedicated Usage + Shared Usage` via typeperf.
- Fallback: RSS proses (perkiraan kasar).
vram_mb = (puncak − sebelum) × 1,05 dibulatkan ke atas kelipatan 100 MB (+ ukuran mmproj)."""

import argparse
import csv
import io
import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._seedfile import load_seed, local_models, patch_model_value  # noqa: E402

GGML_TYPES = {"f16": 1, "q4_0": 2, "q8_0": 8}


# ----------------------------------------------------------------- memori
class GpuMemory:
    """Pembacaan memori GPU proses ini (MB)."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self.method = "rss"
        self._nvml = None
        try:
            import pynvml

            pynvml.nvmlInit()
            self._nvml = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.method = "nvml"
            return
        except Exception:  # noqa: BLE001
            pass
        if sys.platform == "win32" and self._typeperf() is not None:
            self.method = "typeperf"

    def _typeperf(self) -> int | None:
        counters = [
            r"\GPU Process Memory(*)\Dedicated Usage",
            r"\GPU Process Memory(*)\Shared Usage",
        ]
        try:
            out = subprocess.run(
                ["typeperf", *counters, "-sc", "1"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return None
        rows = [r for r in csv.reader(io.StringIO(out)) if len(r) > 1]
        if len(rows) < 2:
            return None
        header, values = rows[0], rows[1]
        tag = f"pid_{self.pid}_"
        total = 0.0
        for name, value in zip(header[1:], values[1:], strict=False):
            if tag in name:
                try:
                    total += float(value)
                except ValueError:
                    pass
        return int(total / 1024 / 1024)

    def read(self) -> int:
        if self.method == "nvml":
            import pynvml

            return int(pynvml.nvmlDeviceGetMemoryInfo(self._nvml).used / 1024 / 1024)
        if self.method == "typeperf":
            return self._typeperf() or 0
        import psutil

        return int(psutil.Process().memory_info().rss / 1024 / 1024)


class PeakSampler(threading.Thread):
    def __init__(self, mem: GpuMemory, interval_s: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.mem, self.interval_s = mem, interval_s
        self.peak = 0
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            self.peak = max(self.peak, self.mem.read())
            self._halt.wait(self.interval_s)

    def stop(self) -> int:
        self._halt.set()
        self.join()
        self.peak = max(self.peak, self.mem.read())
        return self.peak


def round_vram(delta_mb: float) -> int:
    return int(math.ceil(max(delta_mb, 0) * 1.05 / 100.0) * 100)


# ------------------------------------------------------------------ ukur
def measure_gguf(m: dict[str, Any], mem: GpuMemory, fill: float) -> dict[str, Any]:
    import llama_cpp

    if not llama_cpp.llama_supports_gpu_offload():
        raise SystemExit("llama-cpp-python tanpa GPU offload: model akan jalan di CPU (ditolak)")
    cfg = m.get("config") or {}
    path = ROOT / m["artifact_path"]
    if not path.exists():
        return {"alias": m["alias"], "error": f"file tidak ada: {path}"}
    n_ctx = int(cfg.get("n_ctx", 4096))
    kwargs: dict[str, Any] = {
        "model_path": str(path),
        "n_ctx": n_ctx,
        "n_gpu_layers": -1,
        "n_batch": int(cfg.get("n_batch", 512)),
        "verbose": False,
    }
    if cfg.get("flash_attn"):
        kwargs["flash_attn"] = True
    for key in ("type_k", "type_v"):
        if cfg.get(key) in GGML_TYPES:
            kwargs[key] = GGML_TYPES[cfg[key]]
    if cfg.get("embedding"):
        kwargs["embedding"] = True

    before = mem.read()
    sampler = PeakSampler(mem)
    sampler.start()
    t0 = time.perf_counter()
    llm = llama_cpp.Llama(**kwargs)
    load_s = time.perf_counter() - t0
    result: dict[str, Any] = {
        "alias": m["alias"],
        "n_ctx": n_ctx,
        "load_s": round(load_s, 2),
        "method": mem.method,
        "before_mb": before,
    }
    try:
        if cfg.get("embedding"):
            texts = ["kalimat uji embedding " * 20] * 16
            t = time.perf_counter()
            llm.create_embedding(texts)
            result["embed_16_s"] = round(time.perf_counter() - t, 3)
        else:
            filler = llm.tokenize(("Lorem ipsum dolor sit amet. " * 4000).encode())
            prompt = filler[: max(16, int(n_ctx * fill) - 160)]
            t = time.perf_counter()
            ttft = None
            n_out = 0
            for _ in llm.create_completion(
                prompt=prompt, max_tokens=128, stream=True, temperature=0.0
            ):
                if ttft is None:
                    ttft = time.perf_counter() - t
                n_out += 1
            total = time.perf_counter() - t
            gen_s = max(total - (ttft or 0), 1e-6)
            result.update(
                prompt_tokens=len(prompt),
                ttft_s=round(ttft or 0, 2),
                gen_tokens=n_out,
                tok_per_s=round(max(n_out - 1, 0) / gen_s, 1),
            )
    finally:
        peak = sampler.stop()
        del llm
        time.sleep(2)
        result["after_unload_mb"] = mem.read()
    mmproj = cfg.get("mmproj_path")
    mmproj_mb = (
        (ROOT / mmproj).stat().st_size / 1024 / 1024 if mmproj and (ROOT / mmproj).exists() else 0
    )
    result.update(
        peak_mb=peak, mmproj_mb=int(mmproj_mb), vram_mb=round_vram(peak - before + mmproj_mb)
    )
    return result


# ------------------------------------------------------------------ budget
def validate_budget(models: list[dict[str, Any]], measured: dict[str, int]) -> list[str]:
    from app.core.config import get_settings

    s = get_settings()
    report = []

    def vram(m: dict[str, Any]) -> int:
        return int(measured.get(m["alias"], m.get("vram_mb") or 0))

    gpu = [m for m in models if m["device"] == "gpu"]
    npu = [m for m in models if m["device"] == "npu"]
    pinned_gpu = sum(vram(m) for m in gpu if m.get("is_pinned"))
    swap = max((vram(m) for m in gpu if not m.get("is_pinned")), default=0)
    pinned_npu = sum(vram(m) for m in npu if m.get("is_pinned"))
    ok_gpu = pinned_gpu + swap <= s.gpu_budget_mb
    ok_npu = pinned_npu <= s.npu_budget_mb
    report.append(
        f"GPU: pinned {pinned_gpu} + swap terbesar {swap} = {pinned_gpu + swap} MB "
        f"/ budget {s.gpu_budget_mb} MB → {'OK' if ok_gpu else 'MELEBIHI'}"
    )
    report.append(
        f"NPU: pinned {pinned_npu} MB / budget {s.npu_budget_mb} MB → "
        f"{'OK' if ok_npu else 'MELEBIHI'}"
    )
    try:
        import psutil

        ram = psutil.virtual_memory().total // (1024 * 1024)
        worst = pinned_gpu + swap + pinned_npu
        report.append(
            f"UMA: GPU+NPU terpakai maks {worst} MB dari RAM fisik {ram} MB "
            f"({worst / ram:.0%}); sisakan ≥ 4 GB untuk OS/gateway/PostgreSQL"
        )
    except Exception:  # noqa: BLE001
        pass
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--fill", type=float, default=0.8, help="porsi n_ctx untuk prompt (KV cache)")
    ap.add_argument("--update-yaml", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    all_local = local_models(load_seed())
    out_path = ROOT / "logs" / "measure_models.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}

    measured: dict[str, int] = {a: r["vram_mb"] for a, r in previous.items() if "vram_mb" in r}
    if not args.validate_only:
        mem = GpuMemory()
        print(f"metode memori: {mem.method}")
        for m in local_models(load_seed(), only):
            if m.get("runtime_backend") != "llama_cpp_python":
                print(f"{m['alias']}: lewati (NPU/OpenVINO diukur via test_npu.py)")
                continue
            print(f"mengukur {m['alias']} ...", flush=True)
            res = measure_gguf(m, mem, args.fill)
            print(json.dumps(res))
            previous[m["alias"]] = res
            if "vram_mb" in res:
                measured[m["alias"]] = res["vram_mb"]
                if args.update_yaml:
                    patch_model_value(m["alias"], "vram_mb", res["vram_mb"])
        out_path.write_text(json.dumps(previous, indent=2), encoding="utf-8")
    for line in validate_budget(all_local, measured):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
