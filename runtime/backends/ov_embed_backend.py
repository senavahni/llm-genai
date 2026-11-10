"""Backend embedding Qwen3-Embedding lewat OpenVINO GenAI `TextEmbeddingPipeline` (LGW-V1-02):
GPU saja (CPU hanya bila ALLOW_CPU_FALLBACK di test), last-token pooling + L2 normalize di
pipeline, batch, jumlah token dari tokenizer model. Prefix instruksi query diterapkan Gateway;
backend meng-embed teks apa adanya."""

import gc
import time
from typing import Any, ClassVar

import numpy as np

from app.utils.errors import (
    InputTooLong,
    InvalidRequestError,
    ModelLoadFailed,
    UnsupportedParameter,
)
from runtime.backends.base import EmbedPlan, LoadResult, LocalBackend, embedding_response
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
# token ber-padding per batch: lama satu batch ≈ jeda maksimum interactive di bawah beban bulk
DEFAULT_MAX_BATCH_TOKENS = 2048  # benchmark LGW-V1-05: interactive p95 1,6 s di bawah bulk
MAX_INPUTS = 2048
POOLING = {"last_token": "LAST_TOKEN", "mean": "MEAN", "cls": "CLS"}


class OVEmbedBackend(LocalBackend):
    kind: ClassVar[str] = "openvino_embed"

    def __init__(self, spec: LocalModelSpec) -> None:
        super().__init__(spec)
        cfg = spec.config
        self.max_batch = max(1, int(cfg.get("max_batch") or DEFAULT_MAX_BATCH))
        self.max_input_tokens = int(cfg.get("max_input_tokens") or DEFAULT_MAX_INPUT_TOKENS)
        self.max_batch_tokens = max(
            self.max_input_tokens, int(cfg.get("max_batch_tokens") or DEFAULT_MAX_BATCH_TOKENS)
        )
        self.mrl_min_dimensions = int(cfg.get("mrl_min_dimensions") or 0)
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
    def _dimensions(self, value: Any) -> int | None:
        """`dimensions` hanya untuk model MRL (config `mrl_min_dimensions`); None = asli."""
        if value is None or value == self.dimensions:
            return None
        if not isinstance(value, int) or isinstance(value, bool):
            raise InvalidRequestError("dimensions harus bilangan bulat", param="dimensions")
        native = self.dimensions or 0
        if not self.mrl_min_dimensions:
            raise UnsupportedParameter(
                f"Model {self.spec.alias} tidak mendukung parameter dimensions (bukan MRL); "
                f"dimensi tetap {native}",
                param="dimensions",
            )
        if not self.mrl_min_dimensions <= value <= native:
            raise UnsupportedParameter(
                f"dimensions harus {self.mrl_min_dimensions}–{native}", param="dimensions"
            )
        return value

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
        return items

    def _token_counts(self, texts: list[str]) -> list[int]:
        counts = []
        for text in texts:  # satu per satu: tanpa padding, panjang = token sebenarnya
            ids = self._tokenizer.encode(text).input_ids.data
            counts.append(int(ids.shape[-1]))
        return counts

    def _batches(self, texts: list[str], counts: list[int]) -> tuple[tuple[str, ...], ...]:
        """Batch berurutan dengan batas jumlah input DAN token ber-padding (n × terpanjang):
        memori GPU & lama satu batch (= jeda maksimum bagi request interactive) terkendali."""
        out: list[tuple[str, ...]] = []
        cur: list[str] = []
        longest = 0
        for text, n in zip(texts, counts, strict=True):
            grown = max(longest, n)
            if cur and (
                len(cur) >= self.max_batch or grown * (len(cur) + 1) > self.max_batch_tokens
            ):
                out.append(tuple(cur))
                cur, grown = [], n
            cur.append(text)
            longest = grown
        if cur:
            out.append(tuple(cur))
        return tuple(out)

    def _plan_sync(self, req: dict[str, Any]) -> EmbedPlan:
        texts = self._inputs(req)
        dims = self._dimensions(req.get("dimensions"))
        counts = self._token_counts(texts)
        too_long = [i for i, n in enumerate(counts) if n > self.max_input_tokens]
        warnings: tuple[str, ...] = ()
        if too_long and req.get("truncate") is not True:
            raise InputTooLong(
                f"input indeks {too_long[:20]} melebihi {self.max_input_tokens} token; "
                "pecah teks atau kirim provider_options.truncate=true",
                param="input",
            )
        if too_long:  # pipeline memotong ke max_length (EOS tetap), setara truncation HF
            warnings = (f"input_truncated:{len(too_long)}",)
            counts = [min(n, self.max_input_tokens) for n in counts]
        return EmbedPlan(self._batches(texts, counts), sum(counts), dims, warnings)

    async def plan_embeddings(self, req: dict[str, Any]) -> EmbedPlan:
        return await self.run_sync(self._plan_sync, req)

    def _embed_batch_sync(
        self, texts: tuple[str, ...], dimensions: int | None
    ) -> list[list[float]]:
        out = np.asarray(self._pipe.embed_documents(list(texts)), dtype=np.float32)
        if dimensions:  # MRL: ambil d dimensi pertama lalu normalisasi ulang
            out = out[:, :dimensions]
            out /= np.linalg.norm(out, axis=1, keepdims=True)
        return [[float(x) for x in v] for v in out]

    async def embed_batch(
        self, texts: tuple[str, ...], dimensions: int | None
    ) -> list[list[float]]:
        return await self.run_sync(self._embed_batch_sync, texts, dimensions)

    async def embed(self, req: dict[str, Any]) -> dict[str, Any]:
        """Satu request penuh tanpa antrean per batch (test/benchmark); runtime memakai
        plan_embeddings + embed_batch lewat InferenceService."""
        plan = await self.plan_embeddings(req)
        vectors: list[list[float]] = []
        for batch in plan.batches:
            vectors += await self.embed_batch(batch, plan.dimensions)
        return embedding_response(self.spec.upstream_name, vectors, plan)
