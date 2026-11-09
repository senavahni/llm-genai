"""Backend embedding Qwen3-Embedding lewat OpenVINO GenAI `TextEmbeddingPipeline` (LGW-V1-02):
GPU saja (CPU hanya bila ALLOW_CPU_FALLBACK di test), last-token pooling + L2 normalize di
pipeline, batch, jumlah token dari tokenizer model. Prefix instruksi query diterapkan Gateway;
backend meng-embed teks apa adanya."""

import gc
import time
from typing import Any, ClassVar

from app.utils.errors import (
    ContextLengthExceeded,
    InvalidRequestError,
    ModelLoadFailed,
    UnsupportedParameter,
)
from runtime.backends.base import LoadResult, LocalBackend
from runtime.backends.ov_common import (
    cache_dir,
    cache_entries,
    device_kind,
    genai,
    model_path,
    validate_device,
    verify_artifact,
)
from runtime.core.catalog import LocalModelSpec

# batch besar tidak menambah token/s di iGPU tetapi memori naik tajam (docs/hardware.md)
DEFAULT_MAX_BATCH = 8
DEFAULT_MAX_INPUT_TOKENS = 2048
MAX_INPUTS = 2048
POOLING = {"last_token": "LAST_TOKEN", "mean": "MEAN", "cls": "CLS"}


class OVEmbedBackend(LocalBackend):
    kind: ClassVar[str] = "openvino_embed"

    def __init__(self, spec: LocalModelSpec) -> None:
        super().__init__(spec)
        cfg = spec.config
        self.max_batch = max(1, int(cfg.get("max_batch") or DEFAULT_MAX_BATCH))
        self.max_input_tokens = int(cfg.get("max_input_tokens") or DEFAULT_MAX_INPUT_TOKENS)
        self.pooling = str(cfg.get("pooling") or "last_token")
        if self.pooling not in POOLING:
            raise ModelLoadFailed(f"{spec.alias}: config pooling={self.pooling!r} tidak dikenal")
        self._pipe: Any = None
        self._tokenizer: Any = None
        self._device: str | None = None
        self.dimensions: int | None = None

    # ------------------------------------------------------------------ load
    def _config(self, g: Any) -> Any:
        conf = g.TextEmbeddingPipeline.Config()
        conf.pooling_type = getattr(g.TextEmbeddingPipeline.PoolingType, POOLING[self.pooling])
        conf.normalize = True
        # last-token pooling butuh token terakhir di posisi akhir → padding kiri
        conf.padding_side = "left"
        conf.max_length = self.max_input_tokens
        return conf

    def _load_sync(self) -> dict[str, Any]:
        g = genai()
        path = model_path(self.spec)
        verify_artifact(self.spec, path)
        device = validate_device(self.spec.config.get("device") or self.spec.device)
        cdir = cache_dir(self.spec)
        before = cache_entries(cdir)
        start = time.perf_counter()
        pipe = g.TextEmbeddingPipeline(str(path), device, self._config(g), CACHE_DIR=str(cdir))
        compile_ms = int((time.perf_counter() - start) * 1000)
        tokenizer = g.Tokenizer(str(path))
        dims = len(pipe.embed_documents(["warmup"])[0])  # shape pertama + dimensi aktual
        self._pipe, self._tokenizer, self._device, self.dimensions = pipe, tokenizer, device, dims
        return {
            "compile_ms": compile_ms,
            "cache_hit": before > 0 and cache_entries(cdir) == before,
            "dimensions": dims,
            "max_batch": self.max_batch,
            "max_input_tokens": self.max_input_tokens,
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
        self._pipe = self._tokenizer = None
        await self.run_sync(gc.collect)

    def is_loaded(self) -> bool:
        return self._pipe is not None

    def actual_device(self) -> str:
        return device_kind(self._device) if self._device else self.spec.device

    # ------------------------------------------------------------- embedding
    def _inputs(self, req: dict[str, Any]) -> list[str]:
        raw = req.get("input")
        items = [raw] if isinstance(raw, str) else raw
        if not isinstance(items, list) or not items:
            raise InvalidRequestError("Field 'input' wajib berisi teks", param="input")
        if not all(isinstance(t, str) for t in items):
            raise InvalidRequestError("Model lokal hanya menerima input teks", param="input")
        if len(items) > MAX_INPUTS:
            raise InvalidRequestError(f"Maksimal {MAX_INPUTS} input per request", param="input")
        if any(not t for t in items):
            raise InvalidRequestError("Input tidak boleh string kosong", param="input")
        fmt = req.get("encoding_format") or "float"
        if fmt != "float":
            raise UnsupportedParameter(
                "encoding_format model lokal hanya 'float'", param="encoding_format"
            )
        dims = req.get("dimensions")
        if dims is not None and dims != self.dimensions:
            raise UnsupportedParameter(
                f"dimensions {dims} tidak didukung; model ini {self.dimensions}", param="dimensions"
            )
        return items

    def _token_counts(self, texts: list[str]) -> list[int]:
        counts = []
        for text in texts:  # satu per satu: tanpa padding, panjang = token sebenarnya
            ids = self._tokenizer.encode(text).input_ids.data
            counts.append(int(ids.shape[-1]))
        return counts

    def _embed_sync(self, texts: list[str]) -> tuple[list[list[float]], list[int]]:
        counts = self._token_counts(texts)
        too_long = [i for i, n in enumerate(counts) if n > self.max_input_tokens]
        if too_long:
            raise ContextLengthExceeded(
                f"input indeks {too_long[:10]} melebihi {self.max_input_tokens} token",
                param="input",
            )
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.max_batch):
            out = self._pipe.embed_documents(texts[i : i + self.max_batch])
            vectors.extend([float(x) for x in v] for v in out)
        return vectors, counts

    async def embed(self, req: dict[str, Any]) -> dict[str, Any]:
        texts = self._inputs(req)
        vectors, counts = await self.run_sync(self._embed_sync, texts)
        tokens = sum(counts)
        return {
            "object": "list",
            "model": self.spec.upstream_name,
            "data": [
                {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }
