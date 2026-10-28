"""Unduh model OpenVINO IR siap pakai (katalog seed_models.yaml) ke `artifact_path`, hitung sha256.

    scripts\\conda-run.bat python scripts\\download_models.py --dry-run     :: daftar & total ukuran
    scripts\\conda-run.bat python scripts\\download_models.py --only local/qwen2.5-coder-1.5b
    scripts\\conda-run.bat python scripts\\download_models.py --write-yaml  :: tulis artifact_sha256
    lalu: scripts\\conda-run.bat python scripts\\manage.py seed --update-local

Model dengan `convert: true` (Qwen2-VL-2B, SD v1.5) dibuat oleh convert_openvino.py, bukan di
sini. Unduhan lewat HTTPS biasa (scripts/_hfhttp.py): resume, retry, cek ukuran; file yang sudah
lengkap dilewati."""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HOME", str(ROOT / "local_models" / "hf_cache"))

from runtime.core.artifacts import sha256_artifact  # noqa: E402
from scripts._hfhttp import download_file, repo_files  # noqa: E402
from scripts._seedfile import load_seed, local_models, patch_model_value  # noqa: E402

# file repo yang tidak dibutuhkan runtime
SKIP_FILES = {".gitattributes", "README.md"}


def plan(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for m in models:
        if m.get("convert") or not m.get("hf_repo"):
            continue
        sizes = {f: s for f, s in repo_files(m["hf_repo"]).items() if f not in SKIP_FILES}
        items.append({"model": m, "sizes": sizes, "bytes": sum(sizes.values())})
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="alias dipisah koma")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--write-yaml", action="store_true", help="tulis artifact_sha256 ke seed_models.yaml"
    )
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    items = plan(local_models(load_seed(), only))
    for item in items:
        m = item["model"]
        print(
            f"{m['alias']:<28} {item['bytes'] / 1e9:6.2f} GB  {m['hf_repo']} → {m['artifact_path']}"
        )
    print(f"TOTAL {sum(i['bytes'] for i in items) / 1e9:.2f} GB")
    if args.dry_run:
        return 0

    for item in items:
        m = item["model"]
        dest = ROOT / m["artifact_path"]
        print(f"{m['alias']}: mengunduh {item['bytes'] / 1e9:.2f} GB", flush=True)
        for name, size in sorted(item["sizes"].items(), key=lambda kv: kv[1]):
            download_file(m["hf_repo"], name, dest / name, size or None)
        digest = sha256_artifact(dest)
        print(f"{m['alias']}: sha256={digest}", flush=True)
        if args.write_yaml:
            patch_model_value(m["alias"], "artifact_sha256", digest)
    if args.write_yaml:
        print("yaml diperbarui → jalankan: manage.py seed --update-local")
    return 0


if __name__ == "__main__":
    sys.exit(main())
