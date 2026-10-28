"""Factory backend lokal. Modul backend diimpor lazy agar runtime tetap bisa start (dan gateway
tidak pernah mengimpor openvino) walau library akselerator belum terpasang."""

import importlib

from app.utils.errors import ModelLoadFailed
from runtime.backends.base import LocalBackend
from runtime.core.catalog import LocalModelSpec

BACKENDS: dict[str, str] = {
    "openvino_llm": "runtime.backends.ov_llm_backend:OVLLMBackend",  # TASK-11
    "openvino_vlm": "runtime.backends.ov_vlm_backend:OVVLMBackend",  # TASK-11
    "openvino_diffusion": "runtime.backends.ov_diffusion_backend:OVDiffusionBackend",  # TASK-12
}


def backend_class(kind: str) -> type[LocalBackend]:
    target = BACKENDS.get(kind)
    if target is None:
        raise ModelLoadFailed(f"runtime_backend tidak dikenal: {kind!r}")
    module_name, _, class_name = target.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ModelLoadFailed(f"backend {kind} belum tersedia: {exc}") from exc
    cls: type[LocalBackend] = getattr(module, class_name)
    return cls


def create_backend(spec: LocalModelSpec) -> LocalBackend:
    return backend_class(spec.runtime_backend)(spec)
