"""Konversi model OpenVINO (wrapper `optimum-cli export openvino`).

    "%PY%" scripts\\convert_openvino.py --dry-run
    "%PY%" scripts\\convert_openvino.py --only sd15-fp16,bge-m3-int8

Torch hanya dibutuhkan di sini (konversi), tidak saat inferensi runtime. HF_HOME diarahkan ke
local_models/hf_cache. trust_remote_code tidak dipakai (PRD §11.7)."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OV_DIR = ROOT / "local_models" / "openvino"

TARGETS: dict[str, list[str]] = {
    "sd15-fp16": [
        "--model",
        "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "--weight-format",
        "fp16",
    ],
    "sd15-int8": [
        "--model",
        "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "--weight-format",
        "int8",
    ],
    "bge-m3-int8": [
        "--model",
        "BAAI/bge-m3",
        "--task",
        "feature-extraction",
        "--weight-format",
        "int8",
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help=f"dipisah koma; pilihan: {','.join(TARGETS)}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="konversi ulang walau folder sudah ada")
    args = ap.parse_args()

    env = {
        **os.environ,
        "HF_HOME": os.environ.get("HF_HOME") or str(ROOT / "local_models" / "hf_cache"),
    }
    names = args.only.split(",") if args.only else list(TARGETS)
    exe = Path(sys.executable).with_name("Scripts") / "optimum-cli.exe"
    base = [str(exe)] if exe.exists() else [sys.executable, "-m", "optimum.commands.optimum_cli"]
    failed = []
    for name in names:
        out = OV_DIR / name
        cmd = [*base, "export", "openvino", *TARGETS[name], str(out)]
        print(">", " ".join(cmd))
        if args.dry_run:
            continue
        if (out / "model_index.json").exists() or (out / "openvino_model.xml").exists():
            if not args.force:
                print(f"  sudah ada: {out} (pakai --force untuk ulang)")
                continue
        if subprocess.run(cmd, env=env, check=False).returncode != 0:
            failed.append(name)
    if failed:
        print("GAGAL:", ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
