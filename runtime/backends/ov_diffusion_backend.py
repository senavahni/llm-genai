"""Backend Stable Diffusion v1.5 lewat OpenVINO GenAI (TASK-12): text-to-image & image-to-image
dengan satu set model di NPU (atau kombinasi NPU/GPU per komponen), tanpa CPU."""

import asyncio
import base64
import binascii
import gc
import io
import secrets
import time
from dataclasses import dataclass
from typing import Any, ClassVar

from app.utils.errors import (
    InvalidRequestError,
    PayloadTooLarge,
    RequestCancelled,
    UnsupportedParameter,
    UnsupportedSize,
)
from runtime.backends.base import ImageResult, LoadResult, LocalBackend
from runtime.backends.ov_common import (
    cache_dir,
    cache_entries,
    cancel_bridge,
    device_kind,
    genai,
    model_path,
    validate_device,
    verify_artifact,
)
from runtime.core.catalog import LocalModelSpec

COMPONENTS = ("text_encoder", "unet", "vae")
CLIP_MAX_TOKENS = 77
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_N = 4


@dataclass(frozen=True, slots=True)
class _Params:
    prompt: str
    negative_prompt: str | None
    n: int
    steps: int
    guidance_scale: float
    seed: int
    image: bytes | None
    strength: float


class OVDiffusionBackend(LocalBackend):
    kind: ClassVar[str] = "openvino_diffusion"

    def __init__(self, spec: LocalModelSpec) -> None:
        super().__init__(spec)
        self._t2i: Any = None
        self._i2i: Any = None
        self._tokenizer: Any = None
        self._devices: dict[str, str] = {}
        cfg = spec.config
        sizes = [str(s) for s in cfg.get("allowed_sizes") or ["512x512"]]
        self.size = sizes[0]  # v1: satu pipeline (shape statis) per model
        width, _, height = self.size.partition("x")
        self.width, self.height = int(width), int(height)
        self.guidance_scale = float(cfg.get("guidance_scale", 7.5))
        self.default_steps = int(cfg.get("default_steps", 25))
        self.max_steps = int(cfg.get("max_steps", 50))
        self.default_strength = float(cfg.get("default_strength", 0.6))

    # ------------------------------------------------------------------ load
    def component_devices(self) -> dict[str, str]:
        configured = self.spec.config.get("component_devices") or {}
        default = self.spec.config.get("device") or self.spec.device
        return {
            c: validate_device(configured.get(c, default), field=f"component_devices.{c}")
            for c in COMPONENTS
        }

    def _load_sync(self) -> dict[str, Any]:
        g = genai()
        path = model_path(self.spec)
        verify_artifact(self.spec, path)
        devices = self.component_devices()
        cdir = cache_dir(self.spec)
        before = cache_entries(cdir)
        start = time.perf_counter()
        i2i = g.Image2ImagePipeline(str(path))
        i2i.reshape(1, self.height, self.width, self.guidance_scale)
        i2i.compile(*(devices[c] for c in COMPONENTS), CACHE_DIR=str(cdir))
        # satu set model untuk dua mode: UNet/text encoder/VAE tidak dimuat dua kali
        t2i = g.Text2ImagePipeline(i2i)
        compile_ms = int((time.perf_counter() - start) * 1000)
        try:
            tokenizer = g.Tokenizer(str(path / "tokenizer"))
        except Exception:  # noqa: BLE001 - hanya untuk peringatan panjang prompt
            tokenizer = None
        self._i2i, self._t2i, self._tokenizer, self._devices = i2i, t2i, tokenizer, devices
        return {
            "compile_ms": compile_ms,
            "cache_hit": before > 0 and cache_entries(cdir) == before,
            "component_devices": devices,
            "size": self.size,
            "guidance_scale": self.guidance_scale,
        }

    async def load(self) -> LoadResult:
        start = time.perf_counter()
        details = await self.run_sync(self._load_sync)
        return LoadResult(
            load_ms=int((time.perf_counter() - start) * 1000),
            device=self.actual_device(),
            details=details,
        )

    async def unload(self) -> None:
        self._t2i = self._i2i = self._tokenizer = None
        await self.run_sync(gc.collect)

    def is_loaded(self) -> bool:
        return self._t2i is not None

    def actual_device(self) -> str:
        if not self._devices:
            return self.spec.device
        kinds = {device_kind(d) for d in self._devices.values()}
        if "cpu" in kinds:
            return "cpu"
        return device_kind(self._devices["unet"])  # komputasi utama ada di UNet

    # -------------------------------------------------------------- generate
    def _params(self, req: dict[str, Any]) -> _Params:
        prompt = req.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidRequestError("Field 'prompt' wajib diisi", param="prompt")
        if req.get("mask"):
            raise UnsupportedParameter(
                "Inpainting (mask) tidak didukung model lokal ini", param="mask"
            )
        size = str(req.get("size") or self.size)
        if size != self.size:
            raise UnsupportedSize(f"Ukuran {size} tidak didukung; tersedia: {self.size}")
        n = _int(req.get("n", 1), "n")
        if not 1 <= n <= MAX_N:
            raise InvalidRequestError(f"n harus 1–{MAX_N}", param="n")
        steps = _int(req.get("steps") or self.default_steps, "steps")
        if not 1 <= steps <= self.max_steps:
            raise InvalidRequestError(f"steps harus 1–{self.max_steps}", param="steps")
        guidance = req.get("guidance_scale")
        if guidance is not None and abs(float(guidance) - self.guidance_scale) > 1e-6:
            raise UnsupportedParameter(
                f"guidance_scale model ini tetap {self.guidance_scale:g} (shape statis NPU)",
                param="guidance_scale",
            )
        seed = req.get("seed")
        seed = secrets.randbelow(2**31 - MAX_N) if seed is None else _int(seed, "seed")
        if not 0 <= seed <= 2**32 - 1 - MAX_N:
            raise InvalidRequestError("seed harus 0 – 4294967291", param="seed")
        image = _decode_b64(req["image"]) if req.get("image") else None
        strength = float(req.get("strength") or self.default_strength)
        if not 0 < strength <= 1:
            raise InvalidRequestError("strength harus > 0 dan ≤ 1", param="strength")
        negative = req.get("negative_prompt")
        return _Params(
            prompt=prompt,
            negative_prompt=str(negative) if negative else None,
            n=n,
            steps=steps,
            guidance_scale=self.guidance_scale,
            seed=seed,
            image=image,
            strength=strength,
        )

    def _prompt_warnings(self, params: _Params) -> tuple[str, ...]:
        if self._tokenizer is None:
            return ()
        warnings = []
        for name, text in (("prompt", params.prompt), ("negative_prompt", params.negative_prompt)):
            if text and len(self._tokenizer.encode(text).input_ids.data[0]) > CLIP_MAX_TOKENS:
                warnings.append(f"{name}_truncated_to_{CLIP_MAX_TOKENS}_clip_tokens")
        return tuple(warnings)

    def _image_tensor(self, raw: bytes) -> Any:
        import numpy as np
        import openvino as ov
        from PIL import Image, UnidentifiedImageError

        try:
            img = Image.open(io.BytesIO(raw))
            img.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise InvalidRequestError("Field 'image' bukan gambar valid", param="image") from exc
        rgb = img.convert("RGB").resize((self.width, self.height), Image.Resampling.LANCZOS)
        return ov.Tensor(np.asarray(rgb, dtype=np.uint8)[None])

    def _generate_sync(self, params: _Params, image: Any, seed: int, stop: Any) -> bytes:
        from PIL import Image

        g = genai()
        kwargs: dict[str, Any] = {
            "num_inference_steps": params.steps,
            "guidance_scale": params.guidance_scale,
            "generator": g.CppStdGenerator(seed),
            # True = hentikan; dicek tiap step sehingga cancel ≤ 1 step
            "callback": lambda step, num_steps, latent: stop.is_set(),
        }
        if params.negative_prompt:
            kwargs["negative_prompt"] = params.negative_prompt
        if image is not None:
            out = self._i2i.generate(params.prompt, image, strength=params.strength, **kwargs)
        else:
            out = self._t2i.generate(params.prompt, **kwargs)
        if stop.is_set():
            raise RequestCancelled("Image generation dibatalkan")
        buf = io.BytesIO()
        Image.fromarray(out.data[0]).save(buf, format="PNG")
        return buf.getvalue()

    async def generate_images(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> list[ImageResult]:
        params = self._params(req)
        image = await self.run_sync(self._image_tensor, params.image) if params.image else None
        warnings = await self.run_sync(self._prompt_warnings, params)
        results: list[ImageResult] = []
        async with cancel_bridge(cancel) as stop:
            for i in range(params.n):  # berurutan, seed + i
                if stop.is_set():
                    raise RequestCancelled("Image generation dibatalkan")
                png = await self.run_sync(self._generate_sync, params, image, params.seed + i, stop)
                results.append(
                    ImageResult(
                        png_bytes=png,
                        width=self.width,
                        height=self.height,
                        seed=params.seed + i,
                        steps=params.steps,
                        guidance_scale=params.guidance_scale,
                        warnings=warnings,
                    )
                )
        return results


def _int(value: Any, param: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidRequestError(f"{param} harus bilangan bulat", param=param) from exc


def _decode_b64(value: Any) -> bytes:
    if not isinstance(value, str):
        raise InvalidRequestError("Field 'image' harus string base64", param="image")
    data = value.split(",", 1)[1] if value.startswith("data:") else value
    if len(data) * 3 // 4 > MAX_IMAGE_BYTES:
        raise PayloadTooLarge("Gambar maksimal 10 MB", param="image")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidRequestError("Field 'image' bukan base64 valid", param="image") from exc
