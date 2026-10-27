"""Deteksi GPU/NPU yang benar-benar bisa dipakai library inferensi.

- gpu: llama.cpp (llama-cpp-python) dengan GPU offload (CUDA/Vulkan). Info pendukung dari
  OpenVINO device `GPU` (bila GPU Intel) dan `nvidia-smi` (bila NVIDIA).
- npu: OpenVINO device `NPU` (Intel AI Boost).
Import library berat dilakukan di sini (bukan di gateway). Jalankan di thread (blocking)."""

import contextlib
import io
import platform
import shutil
import subprocess
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
    for dev in core.available_devices:
        props: dict[str, Any] = {}
        for prop in _OV_PROPS:
            with contextlib.suppress(Exception):
                props[prop] = str(core.get_property(dev, prop))
        if dev.startswith("NPU"):
            info = result.npu
            info.available = True
            info.name = props.get("FULL_DEVICE_NAME")
            if props.get("NPU_DEVICE_TOTAL_MEM_SIZE"):
                info.total_mem_mb = int(props["NPU_DEVICE_TOTAL_MEM_SIZE"]) // (1024 * 1024)
            info.via.append("openvino")
            info.details["openvino"] = props
        elif dev.startswith("GPU"):
            info = result.gpu
            info.name = info.name or props.get("FULL_DEVICE_NAME")
            if props.get("GPU_DEVICE_TOTAL_MEM_SIZE") and not info.total_mem_mb:
                info.total_mem_mb = int(props["GPU_DEVICE_TOTAL_MEM_SIZE"]) // (1024 * 1024)
            info.details.setdefault("openvino", {})[dev] = props
            info.details["openvino_gpu"] = True


def _probe_llama(result: DeviceProbe) -> None:
    try:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            import llama_cpp

            offload = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"llama_cpp tidak tersedia: {exc}")
        return
    result.system["llama_cpp_version"] = llama_cpp.__version__
    info = result.gpu
    info.details["llama_cpp_gpu_offload"] = offload
    ggml_lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith("ggml_")]
    if ggml_lines:
        info.details["ggml"] = ggml_lines
    if offload:
        info.available = True
        info.via.append("llama_cpp")


def _probe_nvidia(result: DeviceProbe) -> None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"nvidia-smi gagal: {exc}")
        return
    if out:
        name, mem, driver = (x.strip() for x in out.splitlines()[0].split(","))
        result.gpu.name = name
        result.gpu.total_mem_mb = int(float(mem))
        result.gpu.details["nvidia"] = {"driver": driver}


def _probe_system(result: DeviceProbe) -> None:
    result.system["platform"] = platform.platform()
    result.system["python"] = platform.python_version()
    result.system["cpu"] = platform.processor()
    with contextlib.suppress(Exception):
        import psutil

        result.system["ram_total_mb"] = psutil.virtual_memory().total // (1024 * 1024)
        result.system["ram_available_mb"] = psutil.virtual_memory().available // (1024 * 1024)


def detect(*, llama: bool = True, openvino: bool = True) -> DeviceProbe:
    result = DeviceProbe()
    _probe_system(result)
    if openvino:
        _probe_openvino(result)
    _probe_nvidia(result)
    if llama:
        _probe_llama(result)
    # GPU terintegrasi (UMA) berbagi RAM sistem: penting untuk perhitungan budget
    ggml = " ".join(result.gpu.details.get("ggml", []))
    result.gpu.details["uma"] = "uma: 1" in ggml or "iGPU" in (result.gpu.name or "")
    return result
