"""Orkestrasi inferensi runtime: pilih model → lease DeviceManager → panggil backend →
tambahkan `x_runtime` (device, load_ms, queue_ms, infer_ms, backend)."""

import asyncio
import base64
import contextlib
import hashlib
import time
from collections.abc import AsyncIterator
from typing import Any

from app.utils.errors import DeviceUnavailable
from runtime.core import metrics as runtime_metrics
from runtime.core.catalog import LocalModelSpec, RuntimeCatalog
from runtime.device.manager import DeviceManager, Lease


def x_runtime(lease: Lease, infer_ms: int | None) -> dict[str, Any]:
    runtime_metrics.QUEUE_WAIT.labels(lease.spec.alias).observe(lease.queue_ms / 1000)
    return {
        "device": lease.device,
        "backend": lease.spec.runtime_backend,
        "load_ms": lease.load_ms,
        "queue_ms": lease.queue_ms,
        "infer_ms": infer_ms,
    }


def _with_warnings(meta: dict[str, Any], warnings: list[str] | None) -> dict[str, Any]:
    if warnings:
        meta["warnings"] = sorted(set(warnings))
    return meta


class InferenceService:
    def __init__(self, catalog: RuntimeCatalog, managers: dict[str, DeviceManager]) -> None:
        self.catalog = catalog
        self.managers = managers

    def resolve(self, name: str) -> tuple[LocalModelSpec, DeviceManager]:
        spec = self.catalog.get(name)
        manager = self.managers.get(spec.device)
        if manager is None:
            raise DeviceUnavailable(f"device {spec.device} tidak tersedia di runtime ini")
        return spec, manager

    # ------------------------------------------------------------ non-stream
    async def chat(self, body: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        return await self._call("chat", body, request_id)

    async def completion(self, body: dict[str, Any], request_id: str | None) -> dict[str, Any]:
        return await self._call("completion", body, request_id)

    async def _call(
        self, method: str, body: dict[str, Any], request_id: str | None
    ) -> dict[str, Any]:
        spec, manager = self.resolve(body["model"])
        async with manager.acquire(spec, request_id) as lease:
            start = time.perf_counter()
            result: dict[str, Any] = await getattr(lease.backend, method)(body)
            elapsed = time.perf_counter() - start
            result["x_runtime"] = _with_warnings(
                x_runtime(lease, int(elapsed * 1000)), result.pop("_warnings", None)
            )
        usage = result.get("usage") or {}
        runtime_metrics.observe_generation(
            spec.alias, int(usage.get("completion_tokens") or 0), elapsed
        )
        return result

    async def images(
        self, body: dict[str, Any], request_id: str | None, cancel: asyncio.Event
    ) -> dict[str, Any]:
        spec, manager = self.resolve(body["model"])
        async with manager.acquire(spec, request_id) as lease:
            start = time.perf_counter()
            images = await lease.backend.generate_images(body, cancel)
            elapsed = time.perf_counter() - start
            meta = x_runtime(lease, int(elapsed * 1000))
        if images:
            size = f"{images[0].width}x{images[0].height}"
            for _ in images:
                runtime_metrics.IMAGE_SECONDS.labels(spec.alias, size).observe(
                    elapsed / len(images)
                )
        warnings = sorted({w for img in images for w in img.warnings})
        if warnings:
            meta["warnings"] = warnings
        return {
            "created": int(time.time()),
            "data": [
                {
                    "b64_json": base64.b64encode(img.png_bytes).decode(),
                    "sha256": hashlib.sha256(img.png_bytes).hexdigest(),
                    "bytes": len(img.png_bytes),
                    "width": img.width,
                    "height": img.height,
                    "seed": img.seed,
                    "steps": img.steps,
                    "guidance_scale": img.guidance_scale,
                }
                for img in images
            ],
            "x_runtime": meta,
        }

    # ---------------------------------------------------------------- stream
    async def open_stream(
        self, method: str, body: dict[str, Any], request_id: str | None, cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        """Lease diambil SEBELUM respons dimulai (agar model_busy/OOM tetap jadi status HTTP
        yang benar), lalu dilepas saat stream selesai/batal. x_runtime di chunk terakhir."""
        spec, manager = self.resolve(body["model"])
        stack = contextlib.AsyncExitStack()
        lease = await stack.enter_async_context(manager.acquire(spec, request_id))
        try:
            source = getattr(lease.backend, f"{method}_stream")(body, cancel)
        except BaseException:
            await stack.aclose()
            raise
        return self._stream(source, lease, stack, method)

    @staticmethod
    async def _stream(
        source: AsyncIterator[dict[str, Any]],
        lease: Lease,
        stack: contextlib.AsyncExitStack,
        method: str,
    ) -> AsyncIterator[dict[str, Any]]:
        start = time.perf_counter()
        last_id: str | None = None
        warnings: list[str] = []
        completion_tokens = 0
        try:
            async for chunk in source:
                last_id = chunk.get("id", last_id)
                warnings += chunk.pop("_warnings", None) or []
                if chunk.get("usage"):
                    completion_tokens = int(chunk["usage"].get("completion_tokens") or 0)
                yield chunk
            runtime_metrics.observe_generation(
                lease.spec.alias, completion_tokens, time.perf_counter() - start
            )
            yield {
                "id": last_id,
                "object": "chat.completion.chunk" if method == "chat" else "text_completion",
                "model": lease.spec.upstream_name,
                "choices": [],
                "x_runtime": _with_warnings(
                    x_runtime(lease, int((time.perf_counter() - start) * 1000)), warnings
                ),
            }
        finally:
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()
            await stack.aclose()
