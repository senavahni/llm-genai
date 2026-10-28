"""Konversi model OpenVINO yang tidak tersedia sebagai IR siap pakai (wrapper
`optimum-cli export openvino`): Stable Diffusion v1.5 dan Qwen2-VL-2B. Model Qwen2.5 lain
diunduh langsung sebagai IR oleh download_models.py.

    scripts\\conda-run.bat python scripts\\convert_openvino.py --dry-run
    scripts\\conda-run.bat python scripts\\convert_openvino.py --only sd15-int8,qwen2-vl-2b-int4

Bobot sumber diunduh dulu ke local_models/hf_src/ lewat HTTPS biasa (scripts/_hfhttp.py),
karena jalur unduh huggingface_hub macet di jaringan ini; optimum-cli lalu membaca folder lokal.
SD v1.5 memakai file `*.fp16.safetensors` repo (disimpan dengan nama standar) → unduhan ±2,7 GB,
bukan ±5,4 GB; target ekspor memang FP16/INT8. Torch hanya dipakai di sini (konversi).
trust_remote_code tidak dipakai (PRD §11.7)."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.core.artifacts import sha256_artifact  # noqa: E402
from scripts._hfhttp import download_file, repo_files  # noqa: E402
from scripts._seedfile import load_seed, local_models, patch_model_value  # noqa: E402

OV_DIR = ROOT / "local_models" / "openvino"
SRC_DIR = ROOT / "local_models" / "hf_src"

SD_REPO = "stable-diffusion-v1-5/stable-diffusion-v1-5"
# (file di repo, nama lokal)
SourceFiles = list[tuple[str, str | None]]
SD_FILES: SourceFiles = [
    ("model_index.json", None),
    ("scheduler/scheduler_config.json", None),
    ("tokenizer/merges.txt", None),
    ("tokenizer/special_tokens_map.json", None),
    ("tokenizer/tokenizer_config.json", None),
    ("tokenizer/vocab.json", None),
    ("feature_extractor/preprocessor_config.json", None),
    ("text_encoder/config.json", None),
    ("text_encoder/model.fp16.safetensors", "text_encoder/model.safetensors"),
    ("unet/config.json", None),
    ("unet/diffusion_pytorch_model.fp16.safetensors", "unet/diffusion_pytorch_model.safetensors"),
    ("vae/config.json", None),
    ("vae/diffusion_pytorch_model.fp16.safetensors", "vae/diffusion_pytorch_model.safetensors"),
    ("safety_checker/config.json", None),
    ("safety_checker/model.fp16.safetensors", "safety_checker/model.safetensors"),
]
VL_REPO = "Qwen/Qwen2-VL-2B-Instruct"
VL_FILES: SourceFiles = [
    (f, None)
    for f in (
        "config.json",
        "generation_config.json",
        "chat_template.json",
        "preprocessor_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "model.safetensors.index.json",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
    )
]
CODER_REPO = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
CODER_FILES: SourceFiles = [
    (f, None)
    for f in (
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
        "merges.txt",
        "model.safetensors",
    )
]
SOURCES: dict[str, tuple[str, SourceFiles]] = {
    "sd15": (SD_REPO, SD_FILES),
    "qwen2-vl-2b": (VL_REPO, VL_FILES),
    "qwen2.5-coder-1.5b": (CODER_REPO, CODER_FILES),
}
# Dependency khusus konversi, dipasang terpisah (pip --target) dan hanya dimuat proses optimum-cli
# lewat PYTHONPATH, agar env utama tidak di-downgrade. optimum-intel 2.2 menolak ekspor Qwen2-VL
# dengan transformers > 5.0.
TARGET_DEPS: dict[str, list[str]] = {"qwen2-vl-2b-int4": ["transformers==5.0.0"]}
DEPS_DIR = ROOT / "local_models" / "convert_deps"
# LLM di NPU wajib INT4 simetris per-channel; IR `OpenVINO/*-int4-ov` (asimetris, group 128)
# ditolak compiler NPU ("StopLocationVerifierPass ... duplicated names").
NPU_INT4 = ["--weight-format", "int4", "--sym", "--group-size", "-1", "--ratio", "1.0"]

TARGETS: dict[str, tuple[str, list[str]]] = {
    "sd15-fp16": ("sd15", ["--task", "text-to-image", "--weight-format", "fp16"]),
    "sd15-int8": ("sd15", ["--task", "text-to-image", "--weight-format", "int8"]),
    # INT4 untuk bobot LLM; vision encoder & embedding tetap dikompresi INT8 oleh optimum
    "qwen2-vl-2b-int4": (
        "qwen2-vl-2b",
        ["--task", "image-text-to-text", "--weight-format", "int4"],
    ),
    "qwen2.5-coder-1.5b-int4-npu": (
        "qwen2.5-coder-1.5b",
        ["--task", "text-generation-with-past", *NPU_INT4],
    ),
}


def fetch_source(name: str, dry_run: bool) -> Path:
    repo, files = SOURCES[name]
    dest = SRC_DIR / name
    sizes = repo_files(repo)
    missing = [f for f, _ in files if f not in sizes]
    if missing:
        raise SystemExit(f"{repo}: file tidak ada di repo: {missing}")
    total = sum(sizes[f] for f, _ in files)
    print(f"sumber {name}: {repo}, {len(files)} file, {total / 1e9:.2f} GB → {dest}")
    if not dry_run:
        for remote, local in sorted(files, key=lambda f: sizes[f[0]]):
            download_file(repo, remote, dest / (local or remote), sizes[remote] or None)
    return dest


def _isolated_deps(name: str, requirements: list[str]) -> Path:
    target = DEPS_DIR / name
    marker = target / ".installed"
    if marker.exists() and marker.read_text() == "\n".join(requirements):
        return target
    pip = [sys.executable, "-m", "pip", "install", "--no-deps", "--upgrade", "--target"]
    subprocess.run([*pip, str(target), *requirements], check=True)
    marker.write_text("\n".join(requirements))
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help=f"dipisah koma; pilihan: {','.join(TARGETS)}")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="konversi ulang walau folder sudah ada")
    ap.add_argument(
        "--write-yaml",
        action="store_true",
        help="tulis artifact_sha256 model yaml yang artifact_path-nya = hasil konversi",
    )
    args = ap.parse_args()

    env = {
        **os.environ,
        "HF_HOME": os.environ.get("HF_HOME") or str(ROOT / "local_models" / "hf_cache"),
        "HF_HUB_OFFLINE": "1",  # semua bahan sudah lokal; cegah unduhan tersembunyi
    }
    names = args.only.split(",") if args.only else list(TARGETS)
    exe = Path(sys.executable).with_name("Scripts") / "optimum-cli.exe"
    base = [str(exe)] if exe.exists() else [sys.executable, "-m", "optimum.commands.optimum_cli"]
    failed = []
    fetched: dict[str, Path] = {}
    for name in names:
        out = OV_DIR / name
        done_markers = ("model_index.json", "openvino_model.xml", "openvino_language_model.xml")
        if not args.force and any((out / f).exists() for f in done_markers):
            print(f"{name}: sudah ada di {out} (pakai --force untuk ulang)")
            continue
        source, extra = TARGETS[name]
        if source not in fetched:
            fetched[source] = fetch_source(source, args.dry_run)
        cmd = [*base, "export", "openvino", "--model", str(fetched[source]), *extra, str(out)]
        print(">", " ".join(cmd), flush=True)
        if args.dry_run:
            continue
        target_env = dict(env)
        if name in TARGET_DEPS:
            target_env["PYTHONPATH"] = str(_isolated_deps(name, TARGET_DEPS[name]))
        if subprocess.run(cmd, env=target_env, check=False).returncode != 0:
            failed.append(name)
    if args.write_yaml and not args.dry_run:
        for m in local_models(load_seed()):
            name = Path(m["artifact_path"]).name
            if name in names and name not in failed and (OV_DIR / name).exists():
                digest = sha256_artifact(OV_DIR / name)
                patch_model_value(m["alias"], "artifact_sha256", digest)
                print(f"{m['alias']}: sha256={digest}")
    if failed:
        print("GAGAL:", ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
