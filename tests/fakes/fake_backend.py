"""Backend lokal palsu (tanpa hardware). Perilaku diatur lewat spec.config:

- load_delay_s / infer_delay_s : simulasi waktu load & per-token
- oom_above_ctx                : load gagal "out of memory" bila n_ctx > nilai ini
- report_device                : device yang dilaporkan actual_device() (mis. "cpu")
- fail_load                    : pesan error load non-OOM
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

from runtime.backends.base import (
    ImageResult,
    LoadResult,
    LocalBackend,
    iterate_in_thread,
)
from runtime.core.catalog import LocalModelSpec

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


class FakeBackend(LocalBackend):
    kind: ClassVar[str] = "fake"
    instances: ClassVar[list["FakeBackend"]] = []

    def __init__(self, spec: LocalModelSpec) -> None:
        super().__init__(spec)
        self._loaded = False
        self.cancelled = False
        self.last_image_request: dict[str, Any] | None = None
        self.threads: set[str] = set()
        FakeBackend.instances.append(self)

    @property
    def cfg(self) -> dict[str, Any]:
        return self.spec.config

    def _load_sync(self) -> None:
        self.threads.add(threading.current_thread().name)
        time.sleep(float(self.cfg.get("load_delay_s", 0)))
        limit = self.cfg.get("oom_above_ctx")
        if limit is not None and (self.spec.n_ctx or 0) > int(limit):
            raise RuntimeError(
                "Exception from src\\plugins\\intel_npu: ZE_RESULT_ERROR_OUT_OF_DEVICE_MEMORY "
                f"(n_ctx={self.spec.n_ctx})"
            )
        if self.cfg.get("fail_load"):
            raise FileNotFoundError(self.cfg["fail_load"])
        self._loaded = True

    async def load(self) -> LoadResult:
        start = time.perf_counter()
        await self.run_sync(self._load_sync)
        return LoadResult(
            load_ms=int((time.perf_counter() - start) * 1000) or 1, device=self.actual_device()
        )

    async def unload(self) -> None:
        self._loaded = False

    def is_loaded(self) -> bool:
        return self._loaded

    def actual_device(self) -> str:
        return str(self.cfg.get("report_device", self.spec.device))

    def _tokens(self, req: dict[str, Any]) -> list[str]:
        return list(self.cfg.get("tokens", ["Halo", " ", "dunia"]))

    async def chat(self, req: dict[str, Any]) -> dict[str, Any]:
        await self.run_sync(time.sleep, float(self.cfg.get("infer_delay_s", 0)))
        text = "".join(self._tokens(req))
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion",
            "created": 0,
            "model": self.spec.upstream_name,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": text},
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
        }

    def chat_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        tokens = self._tokens(req)
        delay = float(self.cfg.get("infer_delay_s", 0))

        def produce(stop: threading.Event) -> Iterator[dict[str, Any]]:
            for tok in tokens:
                if stop.is_set():
                    self.cancelled = True
                    return
                time.sleep(delay)
                yield {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": self.spec.upstream_name,
                    "choices": [{"index": 0, "delta": {"content": tok}, "finish_reason": None}],
                }
            yield {
                "id": "chatcmpl-fake",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": self.spec.upstream_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": len(tokens),
                    "total_tokens": 4 + len(tokens),
                },
            }

        return iterate_in_thread(self.executor, produce, cancel)

    async def generate_images(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> list[ImageResult]:
        self.last_image_request = req
        n = int(req.get("n", 1))
        seed = int(req.get("seed", 42))
        return [
            ImageResult(
                png_bytes=PNG_1PX,
                width=512,
                height=512,
                seed=seed + i,
                steps=int(req.get("steps", 25)),
                guidance_scale=float(req.get("guidance_scale", 7.5)),
            )
            for i in range(n)
        ]


def spec(
    alias: str, vram_mb: int, *, device: str = "gpu", pinned: bool = False, **config: Any
) -> LocalModelSpec:
    return LocalModelSpec(
        alias=alias,
        upstream_name=alias.split("/")[-1],
        device=device,
        runtime_backend="fake",
        vram_mb=vram_mb,
        is_pinned=pinned,
        config=config,
    )
