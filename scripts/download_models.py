"""Unduh model GGUF katalog (seed_models.yaml) ke local_models/gguf, hitung sha256.

    "%PY%" scripts\\download_models.py --dry-run            :: tampilkan file & total ukuran
    "%PY%" scripts\\download_models.py --only qwen2.5-coder-1.5b,nomic-embed
    "%PY%" scripts\\download_models.py --write-yaml         :: tulis artifact_sha256 ke yaml
    lalu: "%PY%" scripts\\manage.py seed --update-local       :: sinkron ke DB

`filename` boleh pola glob (mis. shard `*-00001-of-*.gguf`); semua shard ikut diunduh dan
llama.cpp memuat dari shard pertama. Unduhan resume otomatis (huggingface_hub)."""

import argparse
import fnmatch
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HOME", str(ROOT / "local_models" / "hf_cache"))
# Transfer Xet macet (0 byte) di jaringan ini; HTTPS biasa dari CDN HF berjalan normal.
# Aktifkan lagi dengan --xet. Harus di-set sebelum huggingface_hub diimpor.
if "--xet" not in sys.argv:
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from scripts._seedfile import load_seed, local_models, patch_model_value  # noqa: E402

GGUF_DIR = ROOT / "local_models" / "gguf"
_SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$")


def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def resolve_files(repo: str, pattern: str, siblings: dict[str, int]) -> list[str]:
    """Pola → daftar file repo. Bila cocok shard, ambil seluruh shard set yang sama."""
    matches = sorted(f for f in siblings if fnmatch.fnmatch(f.lower(), pattern.lower()))
    if not matches:
        raise SystemExit(
            f"{repo}: tidak ada file cocok '{pattern}'. File GGUF tersedia: "
            f"{[f for f in siblings if f.endswith('.gguf')][:20]}"
        )
    first = matches[0]
    shard = _SHARD.search(first)
    if shard:
        prefix = first[: shard.start()]
        return sorted(f for f in siblings if f.startswith(prefix) and _SHARD.search(f))
    return [first]


def plan(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from huggingface_hub import HfApi

    api = HfApi()
    items = []
    for m in models:
        if m.get("runtime_backend") not in ("llama_cpp_python", "llama_server"):
            continue
        info = api.model_info(m["hf_repo"], files_metadata=True)
        siblings = {s.rfilename: s.size or 0 for s in info.siblings or []}
        files = resolve_files(m["hf_repo"], m["filename"], siblings)
        mmproj = (m.get("config") or {}).get("mmproj_filename")
        if mmproj:
            files += resolve_files(m["hf_repo"], mmproj, siblings)
        items.append({"model": m, "files": files, "bytes": sum(siblings[f] for f in files)})
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="alias dipisah koma (boleh tanpa prefix local/)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--xet", action="store_true", help="pakai transfer Xet (default: HTTPS)")
    ap.add_argument(
        "--write-yaml", action="store_true", help="tulis artifact_sha256 ke seed_models.yaml"
    )
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    items = plan(local_models(load_seed(), only))
    total = sum(i["bytes"] for i in items)
    for item in items:
        print(f"{item['model']['alias']:<28} {item['bytes'] / 1e9:6.2f} GB  {item['files']}")
    print(f"TOTAL {total / 1e9:.2f} GB ke {GGUF_DIR}")
    if args.dry_run:
        return 0

    from huggingface_hub import hf_hub_download

    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    for item in items:
        m = item["model"]
        paths = [Path(hf_hub_download(m["hf_repo"], f, local_dir=GGUF_DIR)) for f in item["files"]]
        main_file = paths[0]
        digest = sha256_file(main_file)
        expected = ROOT / m["artifact_path"]
        print(f"{m['alias']}: {main_file.name} sha256={digest}")
        if main_file.resolve() != expected.resolve():
            rel = main_file.relative_to(ROOT).as_posix()
            print(f"  ! artifact_path di yaml ({m['artifact_path']}) != file unduhan ({rel})")
            if args.write_yaml:
                patch_model_value(m["alias"], "artifact_path", rel)
        if args.write_yaml:
            patch_model_value(m["alias"], "artifact_sha256", digest)
    if args.write_yaml:
        print("yaml diperbarui → jalankan: manage.py seed --update-local")
    return 0


if __name__ == "__main__":
    sys.exit(main())
