"""Ukur memori perangkat & performa model LLM OpenVINO (GPU/NPU), SATU PER SATU, lalu validasi
budget §7.5. SD v1.5 diukur lewat test_npu.py.

    scripts\\conda-run.bat python scripts\\measure_models.py --only local/qwen2.5-coder-1.5b
    scripts\\conda-run.bat python scripts\\measure_models.py --only local/qwen2.5-7b --device NPU
    scripts\\conda-run.bat python scripts\\measure_models.py --update-yaml   :: tulis vram_mb
    scripts\\conda-run.bat python scripts\\measure_models.py --validate-only :: cek budget saja
    lalu: scripts\\conda-run.bat python scripts\\manage.py seed --update-local

Memori perangkat (iGPU & NPU Intel = UMA): performance counter Windows
`\\GPU Process Memory(pid_<PID>*)\\Dedicated Usage + Shared Usage` via typeperf (semua adapter
WDDM proses ini, termasuk NPU), dengan RSS proses sebagai pembanding/fallback.
vram_mb = (puncak − sebelum) × 1,05 dibulatkan ke atas kelipatan 100 MB.

Bukti tidak jalan di CPU: `cpu_ratio` = waktu CPU proses / waktu dinding selama generate.
Inferensi di GPU/NPU → CPU hampir menganggur (tokenisasi & sampling saja); inferensi CPU →
mendekati jumlah core."""

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

LLM_BACKENDS = ("openvino_llm", "openvino_vlm")
FILLER = "The quick brown fox jumps over the lazy dog while the gateway routes requests. "


# ----------------------------------------------------------------- memori
class DeviceMemory:
    """Memori perangkat (GPU/NPU) yang dialokasikan proses ini, dalam MB."""

    def __init__(self) -> None:
        self.pid = os.getpid()
        self.method = (
            "typeperf" if sys.platform == "win32" and self._typeperf() is not None else "rss"
        )

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

    @staticmethod
    def rss() -> int:
        import psutil

        return int(psutil.Process().memory_info().rss / 1024 / 1024)

    def read(self) -> int:
        if self.method == "typeperf":
            return self._typeperf() or 0
        return self.rss()


class PeakSampler(threading.Thread):
    def __init__(self, mem: DeviceMemory, interval_s: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.mem, self.interval_s = mem, interval_s
        self.peak = 0
        self.peak_rss = 0
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            self.peak = max(self.peak, self.mem.read())
            self.peak_rss = max(self.peak_rss, self.mem.rss())
            self._halt.wait(self.interval_s)

    def stop(self) -> tuple[int, int]:
        self._halt.set()
        self.join()
        self.peak = max(self.peak, self.mem.read())
        self.peak_rss = max(self.peak_rss, self.mem.rss())
        return self.peak, self.peak_rss


def round_vram(delta_mb: float) -> int:
    return int(math.ceil(max(delta_mb, 0) * 1.05 / 100.0) * 100)


# ------------------------------------------------------------------ ukur
def pipeline_properties(m: dict[str, Any], device: str) -> dict[str, Any]:
    """Properti OpenVINO GenAI per device (sama dengan backend runtime TASK-11)."""
    cfg = m.get("config") or {}
    props: dict[str, Any] = {"CACHE_DIR": str(ROOT / cfg.get("cache_dir", "local_models/ov_cache"))}
    if device == "NPU":
        props["MAX_PROMPT_LEN"] = int(cfg.get("max_prompt_len", 1024))
        props["MIN_RESPONSE_LEN"] = int(cfg.get("min_response_len", 128))
    return props


def _prompt_of(tokenizer: Any, n_tokens: int) -> str:
    ids = tokenizer.encode(FILLER * (n_tokens // 10 + 10)).input_ids.data[0][:n_tokens]
    return str(tokenizer.decode(list(ids)))


def measure_llm(
    m: dict[str, Any], mem: DeviceMemory, device: str, prompt_tokens: list[int]
) -> dict[str, Any]:
    import openvino_genai as ov_genai
    import psutil

    path = ROOT / m["artifact_path"]
    if not path.exists():
        return {"alias": m["alias"], "device": device, "error": f"artefak tidak ada: {path}"}
    if m["runtime_backend"] == "openvino_vlm":
        cls = ov_genai.VLMPipeline
    else:
        cls = ov_genai.LLMPipeline
    proc = psutil.Process()
    before, before_rss = mem.read(), mem.rss()
    sampler = PeakSampler(mem)
    sampler.start()
    t0 = time.perf_counter()
    try:
        pipe = cls(str(path), device, **pipeline_properties(m, device))
    except Exception as exc:  # noqa: BLE001 - mis. compiler NPU menolak model; JANGAN coba CPU
        sampler.stop()
        return {
            "alias": m["alias"],
            "device": device,
            "error": f"load gagal: {type(exc).__name__}: {str(exc).splitlines()[-1][:300]}",
        }
    result: dict[str, Any] = {
        "alias": m["alias"],
        "device": device,
        "load_s": round(time.perf_counter() - t0, 2),
        "method": mem.method,
        "before_mb": before,
        "runs": [],
    }
    try:
        tokenizer = pipe.get_tokenizer()
        cfg = ov_genai.GenerationConfig()
        cfg.max_new_tokens = 128
        cfg.ignore_eos = True  # selalu 128 token agar token/s sebanding
        for n in prompt_tokens:
            prompt = _prompt_of(tokenizer, n)
            cpu0, wall0 = proc.cpu_times(), time.perf_counter()
            if cls is ov_genai.VLMPipeline:
                res = pipe.generate(prompt, generation_config=cfg)
            else:
                res = pipe.generate([prompt], cfg)
            wall = time.perf_counter() - wall0
            cpu1 = proc.cpu_times()
            cpu_s = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
            pm = res.perf_metrics
            result["runs"].append(
                {
                    "prompt_tokens": int(pm.get_num_input_tokens()),
                    "ttft_s": round(pm.get_ttft().mean / 1000, 2),
                    "gen_tokens": int(pm.get_num_generated_tokens()),
                    "tok_per_s": round(pm.get_throughput().mean, 1),
                    "wall_s": round(wall, 2),
                    "cpu_ratio": round(cpu_s / max(wall, 1e-6), 2),
                }
            )
            print(f"  {n} token: {result['runs'][-1]}", flush=True)
    except Exception as exc:  # noqa: BLE001 - catat (mis. prompt > MAX_PROMPT_LEN NPU)
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        peak, peak_rss = sampler.stop()
        del pipe
        time.sleep(2)
        result["after_unload_mb"] = mem.read()
    result.update(
        peak_mb=peak,
        rss_delta_mb=peak_rss - before_rss,
        cpu_count=psutil.cpu_count(),
        vram_mb=round_vram(peak - before if mem.method == "typeperf" else peak_rss - before_rss),
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
    swap_npu = max((vram(m) for m in npu if not m.get("is_pinned")), default=0)
    ok_gpu = pinned_gpu + swap <= s.gpu_budget_mb
    ok_npu = pinned_npu + swap_npu <= s.npu_budget_mb
    report.append(
        f"GPU: pinned {pinned_gpu} + swap terbesar {swap} = {pinned_gpu + swap} MB "
        f"/ budget {s.gpu_budget_mb} MB → {'OK' if ok_gpu else 'MELEBIHI'}"
    )
    report.append(
        f"NPU: pinned {pinned_npu} + swap terbesar {swap_npu} = {pinned_npu + swap_npu} MB "
        f"/ budget {s.npu_budget_mb} MB → {'OK' if ok_npu else 'MELEBIHI'}"
    )
    try:
        import psutil

        ram = psutil.virtual_memory().total // (1024 * 1024)
        worst = pinned_gpu + swap + pinned_npu + swap_npu
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
    ap.add_argument("--device", choices=["GPU", "NPU"], help="paksa device (default: yaml)")
    ap.add_argument("--prompt-tokens", default="512,2048", help="panjang prompt uji, dipisah koma")
    ap.add_argument("--update-yaml", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None
    all_local = local_models(load_seed())
    out_path = ROOT / "logs" / "measure_models.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}

    measured: dict[str, int] = {}
    if not args.validate_only:
        mem = DeviceMemory()
        print(f"metode memori: {mem.method}")
        lengths = [int(x) for x in args.prompt_tokens.split(",")]
        for m in local_models(load_seed(), only):
            if m.get("runtime_backend") not in LLM_BACKENDS:
                print(f"{m['alias']}: lewati (SD diukur via test_npu.py)")
                continue
            device = args.device or str((m.get("config") or {}).get("device", "GPU"))
            print(f"mengukur {m['alias']} di {device} ...", flush=True)
            res = measure_llm(m, mem, device, lengths)
            print(json.dumps(res))
            previous[f"{m['alias']}@{device}"] = res
            # simpan tiap model: proses yang crash di model berikutnya tidak menghapus hasil
            out_path.write_text(json.dumps(previous, indent=2), encoding="utf-8")
            on_yaml_device = device == str((m.get("config") or {}).get("device", "GPU"))
            if "error" not in res and on_yaml_device:
                measured[m["alias"]] = res["vram_mb"]
                if args.update_yaml:
                    patch_model_value(m["alias"], "vram_mb", res["vram_mb"])
    for line in validate_budget(all_local, measured):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
