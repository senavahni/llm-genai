"""Deteksi GPU/NPU yang benar-benar bisa dipakai OpenVINO (satu-satunya stack inferensi lokal).

- gpu: OpenVINO device `GPU` (Intel iGPU/Arc).
- npu: OpenVINO device `NPU` (Intel AI Boost).
Device `CPU` sengaja tidak dilaporkan sebagai target inferensi. Import library berat dilakukan
di sini (bukan di gateway). Jalankan di thread (blocking)."""

import contextlib
import platform
from dataclasses import asdict, dataclass, field
from typing import Any

_OV_PROPS = (
    "FULL_DEVICE_NAME",
    "DEVICE_ARCHITECTURE",
    "DEVICE_TYPE",
    "GPU_DEVICE_TOTAL_MEM_SIZE",
    "NPU_DEVICE_TOTAL_MEM_SIZE",
    "NPU_DRIVER_VERSION",
    "OPTIMIZATION_CAPABILITIES",
)


@dataclass
class DeviceInfo:
    available: bool = False
    name: str | None = None
    total_mem_mb: int | None = None
    via: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceProbe:
    gpu: DeviceInfo = field(default_factory=DeviceInfo)
    npu: DeviceInfo = field(default_factory=DeviceInfo)
    system: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def available(self, device: str) -> bool:
        info = getattr(self, device, None)
        return bool(info and info.available)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _probe_openvino(result: DeviceProbe) -> None:
    try:
        import openvino as ov
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"openvino tidak tersedia: {exc}")
        return
    core = ov.Core()
    result.system["openvino_version"] = ov.__version__
    result.system["openvino_devices"] = list(core.available_devices)
    with contextlib.suppress(Exception):
        import openvino_genai

        result.system["openvino_genai_version"] = openvino_genai.__version__
    for dev in core.available_devices:
        props: dict[str, Any] = {}
        for prop in _OV_PROPS:
            with contextlib.suppress(Exception):
                props[prop] = str(core.get_property(dev, prop))
        if dev.startswith("NPU"):
            info = result.npu
            if props.get("NPU_DEVICE_TOTAL_MEM_SIZE"):
                info.total_mem_mb = int(props["NPU_DEVICE_TOTAL_MEM_SIZE"]) // (1024 * 1024)
        elif dev.startswith("GPU"):
            info = result.gpu
            if props.get("GPU_DEVICE_TOTAL_MEM_SIZE") and not info.total_mem_mb:
                info.total_mem_mb = int(props["GPU_DEVICE_TOTAL_MEM_SIZE"]) // (1024 * 1024)
            # iGPU (UMA) berbagi RAM sistem: penting untuk perhitungan budget
            info.details["uma"] = "INTEGRATED" in props.get("DEVICE_TYPE", "").upper()
        else:
            continue
        info.available = True
        info.name = info.name or props.get("FULL_DEVICE_NAME")
        if "openvino" not in info.via:
            info.via.append("openvino")
        info.details.setdefault("openvino", {})[dev] = props


def _probe_system(result: DeviceProbe) -> None:
    result.system["platform"] = platform.platform()
    result.system["python"] = platform.python_version()
    result.system["cpu"] = platform.processor()
    with contextlib.suppress(Exception):
        import psutil

        result.system["ram_total_mb"] = psutil.virtual_memory().total // (1024 * 1024)
        result.system["ram_available_mb"] = psutil.virtual_memory().available // (1024 * 1024)


def detect(*, openvino: bool = True) -> DeviceProbe:
    result = DeviceProbe()
    _probe_system(result)
    if openvino:
        _probe_openvino(result)
    return result
