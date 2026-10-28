"""Kontrak backend lokal + utilitas eksekusi native di thread (non-blocking event loop)."""

import asyncio
import contextlib
import functools
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from app.utils.errors import CapabilityNotSupported
from runtime.core.catalog import LocalModelSpec

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LoadResult:
    load_ms: int
    device: str  # device aktual setelah load
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImageResult:
    png_bytes: bytes
    width: int
    height: int
    seed: int
    steps: int
    guidance_scale: float


class LocalBackend(ABC):
    kind: ClassVar[str]  # openvino_llm | openvino_vlm | openvino_diffusion

    def __init__(self, spec: LocalModelSpec) -> None:
        self.spec = spec
        self.device = spec.device
        self.executor: Executor | None = None  # di-set DeviceManager (thread pool per device)

    async def run_sync(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Jalankan panggilan native di thread pool device, bukan di event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, functools.partial(fn, *args, **kwargs))

    @abstractmethod
    async def load(self) -> LoadResult: ...

    @abstractmethod
    async def unload(self) -> None: ...

    @abstractmethod
    def is_loaded(self) -> bool: ...

    @abstractmethod
    def actual_device(self) -> str:
        """Device aktual setelah load (anti-CPU): gpu | npu | cpu."""

    # ---------------------------------------- kapabilitas opsional (format OpenAI)
    async def chat(self, req: dict[str, Any]) -> dict[str, Any]:
        raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung chat")

    def chat_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung chat")

    async def completion(self, req: dict[str, Any]) -> dict[str, Any]:
        raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung completions")

    def completion_stream(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung completions")

    async def generate_images(
        self, req: dict[str, Any], cancel: asyncio.Event
    ) -> list[ImageResult]:
        """text-to-image; image-to-image bila `req` berisi `image` (base64) + `strength`."""
        raise CapabilityNotSupported(f"{self.spec.alias} tidak mendukung image generation")


async def iterate_in_thread(
    executor: Executor | None,
    producer: Callable[[threading.Event], Iterator[T]],
    cancel: asyncio.Event | None = None,
) -> AsyncIterator[T]:
    """Generator native (blocking) di thread → async generator via asyncio.Queue.

    `producer(stop)` menerima threading.Event yang di-set saat client batal/disconnect; producer
    wajib memeriksanya tiap token/step. Generator ini baru selesai setelah thread berhenti,
    sehingga instans model tidak pernah dipakai dua thread sekaligus setelah lease dilepas."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[int, Any]] = asyncio.Queue()
    stop = threading.Event()

    def put(item: tuple[int, Any]) -> None:
        with contextlib.suppress(RuntimeError):  # loop sudah ditutup
            loop.call_soon_threadsafe(queue.put_nowait, item)

    def worker() -> None:
        try:
            for item in producer(stop):
                put((0, item))
                if stop.is_set():
                    break
            put((1, None))
        except BaseException as exc:  # noqa: BLE001 - diteruskan ke consumer
            put((2, exc))

    async def watch_cancel() -> None:
        if cancel is not None:
            await cancel.wait()
            stop.set()

    future = loop.run_in_executor(executor, worker)
    watcher = asyncio.ensure_future(watch_cancel())
    try:
        while True:
            kind, value = await queue.get()
            if kind == 1:
                break
            if kind == 2:
                raise value
            yield value
    finally:
        stop.set()
        watcher.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.shield(future)
