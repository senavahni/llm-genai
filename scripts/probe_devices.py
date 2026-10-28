"""Identifikasi hardware untuk inferensi lokal → logs/device_probe.json + ringkasan di layar.

scripts\\conda-run.bat python scripts\\probe_devices.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.device.probe import detect  # noqa: E402


def recommendations(probe: dict) -> list[str]:
    rec = []
    gpu, npu, system = probe["gpu"], probe["npu"], probe["system"]
    if "openvino_genai_version" not in system:
        rec.append("openvino-genai belum terpasang: pip install -r requirements-local.txt")
    if not gpu["available"]:
        rec.append("GPU tidak terdeteksi OpenVINO: cek driver Intel Graphics")
    if not npu["available"]:
        rec.append("NPU tidak terdeteksi OpenVINO: cek driver Intel NPU (butuh admin/IT)")
    if gpu["details"].get("uma"):
        ram = system.get("ram_total_mb")
        rec.append(
            f"GPU terintegrasi (UMA): VRAM = RAM sistem bersama ({ram} MB total), dipakai juga "
            "oleh NPU dan OS. Jumlah GPU_BUDGET + NPU_BUDGET harus muat di RAM fisik."
        )
    return rec


def main() -> int:
    probe = detect().to_dict()
    probe["recommendations"] = recommendations(probe)
    out = ROOT / "logs" / "device_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(probe, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"GPU : available={probe['gpu']['available']} name={probe['gpu']['name']} "
        f"mem={probe['gpu']['total_mem_mb']} MB via={probe['gpu']['via']}"
    )
    print(
        f"NPU : available={probe['npu']['available']} name={probe['npu']['name']} "
        f"mem={probe['npu']['total_mem_mb']} MB via={probe['npu']['via']}"
    )
    print(
        f"RAM : {probe['system'].get('ram_total_mb')} MB total, "
        f"{probe['system'].get('ram_available_mb')} MB tersedia"
    )
    for line in probe["recommendations"]:
        print(" -", line)
    for err in probe["errors"]:
        print(" ! ", err)
    print(f"\nDetail: {out}")
    return 0 if probe["gpu"]["available"] and probe["npu"]["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
