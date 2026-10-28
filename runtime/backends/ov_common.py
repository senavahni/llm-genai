"""Utilitas bersama backend OpenVINO: validasi device (anti-CPU), verifikasi artefak, cache
compile, dan jembatan cancel asyncio → thread native."""

import asyncio
import contextlib
import importlib
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any

from app.core.config import get_settings
from app.utils.errors import ModelLoadFailed
from app.utils.logger import get_logger
from runtime.core.artifacts import sha256_artifact
from runtime.core.catalog import LocalModelSpec

log = get_logger("runtime.backends")

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_DEVICES = ("GPU", "NPU")
# device OpenVINO yang bisa diam-diam berjalan di CPU
_CPU_LIKE = ("CPU", "AUTO", "HETERO", "MULTI", "BATCH")

_verified: dict[str, str] = {}  # path artefak → sha256 yang sudah cocok (cache per proses)


def genai() -> ModuleType:
    """Import `openvino_genai` saat dibutuhkan (diganti modul palsu di unit test)."""
    return importlib.import_module("openvino_genai")


def validate_device(value: Any, *, field: str = "device") -> str:
    """`GPU`, `GPU.<n>`, `NPU` saja. CPU/AUTO/HETERO/MULTI hanya bila ALLOW_CPU_FALLBACK."""
    device = str(value or "").strip().upper()
    base = device.split(".", 1)[0].split(":", 1)[0]
    if base in ALLOWED_DEVICES:
        return device
    if base in _CPU_LIKE and get_settings().allow_cpu_fallback:
        log.warning("cpu_device_allowed_by_fallback", field=field, device=device)
        return device
    raise ModelLoadFailed(
        f"config {field}={value!r} ditolak: hanya GPU/NPU (inferensi CPU dilarang, "
        "ALLOW_CPU_FALLBACK=false)"
    )


def device_kind(device: str) -> str:
    """Device OpenVINO → nilai device runtime (`gpu`/`npu`/`cpu`)."""
    base = device.upper().split(".", 1)[0]
    return {"GPU": "gpu", "NPU": "npu"}.get(base, "cpu")


def resolve_path(path: str | None) -> Path:
    if not path:
        raise ModelLoadFailed("artifact_path kosong")
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def model_path(spec: LocalModelSpec) -> Path:
    path = resolve_path(spec.artifact_path)
    if not path.exists():
        raise ModelLoadFailed(f"{spec.alias}: artefak tidak ditemukan: {path}")
    return path


def verify_artifact(spec: LocalModelSpec, path: Path) -> None:
    """Cocokkan digest folder IR dengan `artifact_sha256` (sekali per proses per path)."""
    expected = (spec.artifact_sha256 or "").strip().lower()
    if not expected:
        log.warning("artifact_sha256_missing", model=spec.alias)
        return
    key = str(path)
    if _verified.get(key) == expected:
        return
    actual = sha256_artifact(path)
    if actual != expected:
        raise ModelLoadFailed(
            f"{spec.alias}: sha256 artefak tidak cocok (katalog {expected[:12]}…, "
            f"file {actual[:12]}…); unduh/konversi ulang model"
        )
    _verified[key] = expected


def cache_dir(spec: LocalModelSpec) -> Path:
    configured = spec.config.get("cache_dir") or get_settings().ov_cache_dir
    path = resolve_path(str(configured))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_entries(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file())


@contextlib.asynccontextmanager
async def cancel_bridge(cancel: asyncio.Event | None) -> AsyncIterator[threading.Event]:
    """threading.Event yang di-set saat `cancel` (asyncio) di-set; dibaca callback native."""
    stop = threading.Event()

    async def watch() -> None:
        if cancel is not None:
            await cancel.wait()
            stop.set()

    task = asyncio.ensure_future(watch())
    try:
        yield stop
    finally:
        task.cancel()
        with contextlib.suppress(BaseException):
            await task
