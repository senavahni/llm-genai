"""Benchmark embedding lokal Qwen3-Embedding di GPU (LGW-V1-05). Hasil JSON di
local_models/spike/bench/, ringkasan ditulis manual ke docs/perf-report.md.

    scripts\\conda-run.bat python scripts\\bench_embed.py throughput
    scripts\\conda-run.bat python scripts\\bench_embed.py latency
    scripts\\conda-run.bat python scripts\\bench_embed.py quality    :: butuh OPENAI_API_KEY

- throughput: chunk 200/500/800/1.000 token × batch 8/16/32/64 → chunk/s, token/s, memori puncak
  perangkat (counter Windows, sama dengan measure_models.py). Kombinasi dengan token ber-padding
  per batch > --max-batch-tokens tidak dijalankan (memori bisa melewati budget GPU / RAM UMA).
- latency: InferenceService + DeviceManager sungguhan; job bulk berjalan, query interactive
  dikirim berkala → p50/p95/maks latensi interactive, untuk beberapa nilai max_batch_tokens.
- quality: recall@6 dense `local/qwen3-embedding-0.6b` (query ber-prefix instruksi) vs
  `openai/text-embedding-3-small` (embed-default) atas set eval KB MCP (3 brief, 30 pertanyaan).
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.backends.ov_embed_backend import OVEmbedBackend  # noqa: E402
from runtime.core.catalog import LocalModelSpec, RuntimeCatalog  # noqa: E402
from runtime.device.manager import DeviceManager  # noqa: E402
from runtime.services.inference_service import InferenceService  # noqa: E402
from scripts._embed_eval_set import QUERY_PREFIX, eval_set  # noqa: E402
from scripts._seedfile import load_seed, local_models  # noqa: E402
from scripts.measure_models import DeviceMemory  # noqa: E402

ALIAS = "local/qwen3-embedding-0.6b"
OUT = ROOT / "local_models" / "spike" / "bench"
MCP_EVAL = ROOT.parent / "mcp" / "tests" / "eval" / "kb"
TOP_K = 6


def catalog_spec(**config: Any) -> LocalModelSpec:
    m = next(x for x in local_models(load_seed()) if x["alias"] == ALIAS)
    return LocalModelSpec(
        alias=ALIAS,
        upstream_name=m["upstream_name"],
        device=m["device"],
        runtime_backend=m["runtime_backend"],
        model_type=m["model_type"],
        artifact_path=m["artifact_path"],
        artifact_sha256=m.get("artifact_sha256"),
        vram_mb=int(m["vram_mb"]),
        is_pinned=True,
        config={**m["config"], **config},
    )


def save(name: str, data: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(json.dumps(data, indent=2, ensure_ascii=False))


class PeakMemory:
    """Sampling memori perangkat proses ini di thread terpisah selama blok `with`."""

    def __init__(self, mem: DeviceMemory) -> None:
        self.mem, self.peak, self._stop = mem, 0, threading.Event()

    def __enter__(self) -> "PeakMemory":
        def run() -> None:
            while not self._stop.is_set():
                self.peak = max(self.peak, self.mem.read())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join()


def make_chunks(backend: OVEmbedBackend, tokens: int, n: int) -> list[str]:
    """n teks ±`tokens` token (termasuk EOS) dengan isi berbeda, dari korpus set kesetaraan."""
    corpus = " ".join(t for _, t in eval_set())
    ids = backend._tokenizer.encode(corpus).input_ids.data[0].tolist()[:-1]  # noqa: SLF001
    ids = ids * (tokens * n // len(ids) + 2)
    step = max(1, len(ids) // (n + 1) - tokens) if n > 1 else 0
    out = []
    for i in range(n):
        start = (i * (tokens + step)) % (len(ids) - tokens)
        out.append(backend._tokenizer.decode([ids[start : start + tokens - 1]])[0])  # noqa: SLF001
    return out


# ------------------------------------------------------------------ throughput
async def throughput(args: argparse.Namespace) -> None:
    mem = DeviceMemory()
    backend = OVEmbedBackend(catalog_spec(max_batch=64, max_batch_tokens=10**6))
    load = await backend.load()
    await backend.embed({"input": make_chunks(backend, 200, 8)})  # pemanasan kernel GPU
    base = mem.read()
    rows = []
    for tokens in (200, 500, 800, 1000):
        for batch in (8, 16, 32, 64):
            if tokens * batch > args.max_batch_tokens:
                rows.append({"tokens": tokens, "batch": batch, "skipped": "memori"})
                continue
            texts = make_chunks(backend, tokens, batch * args.batches)
            backend.max_batch = batch
            with PeakMemory(mem) as peak:
                start = time.perf_counter()
                resp = await backend.embed({"input": texts})
                dt = time.perf_counter() - start
            n_tok = resp["usage"]["prompt_tokens"]
            rows.append(
                {
                    "tokens": tokens,
                    "batch": batch,
                    "tokens_avg": round(n_tok / len(texts), 1),
                    "chunks_per_s": round(len(texts) / dt, 2),
                    "tokens_per_s": round(n_tok / dt),
                    "peak_mb": peak.peak,
                }
            )
            print(rows[-1], flush=True)
    save("throughput", {"load_ms": load.load_ms, "after_load_mb": base, "rows": rows})


# --------------------------------------------------------------------- latency
async def latency(args: argparse.Namespace) -> None:
    results = []
    for budget in args.budgets:
        spec = catalog_spec(max_batch_tokens=budget)
        catalog = RuntimeCatalog(session_factory=None)  # type: ignore[arg-type]
        catalog.set({spec.upstream_name: spec})
        manager = DeviceManager("gpu", 5300, queue_timeout_s=120, min_residency_s=0)
        svc = InferenceService(catalog, {"gpu": manager})
        await manager.load(spec, pin=True)
        backend = next(iter(manager._loaded.values())).backend  # noqa: SLF001
        assert isinstance(backend, OVEmbedBackend)
        bulk_texts = make_chunks(backend, args.bulk_tokens, args.bulk_chunks)
        query = QUERY_PREFIX + "Siapa pesaing utama kami di pasar minuman siap saji?"
        base = await _timed(svc, [query], "interactive")
        bulk_task = asyncio.ensure_future(_timed(svc, bulk_texts, "bulk"))
        lat: list[float] = []
        await asyncio.sleep(1.0)
        while not bulk_task.done():
            lat.append(await _timed(svc, [query], "interactive"))
            await asyncio.sleep(args.probe_interval)
        bulk_s = await bulk_task
        await manager.unload_all("bench")
        manager.close()
        row = {
            "max_batch_tokens": budget,
            "idle_interactive_ms": round(base * 1000),
            "probes": len(lat),
            "interactive_p50_ms": round(statistics.median(lat) * 1000) if lat else None,
            "interactive_p95_ms": round(np.percentile(lat, 95) * 1000) if lat else None,
            "interactive_max_ms": round(max(lat) * 1000) if lat else None,
            "bulk_chunks": args.bulk_chunks,
            "bulk_tokens_each": args.bulk_tokens,
            "bulk_s": round(bulk_s, 1),
            "bulk_chunks_per_s": round(args.bulk_chunks / bulk_s, 2),
        }
        results.append(row)
        print(row, flush=True)
    save("latency", {"rows": results})


async def _timed(svc: InferenceService, texts: list[str], priority: str) -> float:
    start = time.perf_counter()
    await svc.embeddings({"model": ALIAS, "input": texts, "priority": priority}, None)
    return time.perf_counter() - start


# --------------------------------------------------------------------- quality
def kb_chunks() -> list[tuple[str, str]]:
    """Brief MCP dipecah per bagian (judul `##` + isi) → (doc, teks)."""
    out = []
    for path in sorted((MCP_EVAL / "briefs").glob("*.md")):
        body = path.read_text(encoding="utf-8")
        for part in body.split("\n## "):
            text = part.strip().lstrip("# ").strip()
            if text:
                out.append((path.stem, text))
    return out


def recall(
    q_vecs: np.ndarray, c_vecs: np.ndarray, questions: list[dict], chunks: list
) -> dict[str, float]:
    """recall@k (k = 1, 3, 6): ada chunk berisi jawaban di top-k. Pool kecil (24 chunk) membuat
    @6 cepat jenuh, jadi @1/@3 ikut dilaporkan."""
    out = {}
    for k in (1, 3, TOP_K):
        hits = 0
        for qv, item in zip(q_vecs, questions, strict=True):
            top = np.argsort(-(c_vecs @ qv))[:k]
            hits += any(item["expect"].lower() in chunks[i][1].lower() for i in top)
        out[f"recall@{k}"] = round(hits / len(questions), 3)
    return out


async def quality(args: argparse.Namespace) -> None:
    questions = [
        json.loads(x)
        for x in (MCP_EVAL / "questions.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    chunks = kb_chunks()
    texts = [t for _, t in chunks]
    backend = OVEmbedBackend(catalog_spec())
    await backend.load()

    async def local(items: list[str]) -> np.ndarray:
        resp = await backend.embed({"input": items})
        return np.array([d["embedding"] for d in resp["data"]])

    result: dict[str, Any] = {"chunks": len(chunks), "questions": len(questions), "top_k": TOP_K}
    c_local = await local(texts)
    result["local_query_prefix"] = recall(
        await local([QUERY_PREFIX + q["q"] for q in questions]), c_local, questions, chunks
    )
    result["local_no_prefix"] = recall(
        await local([q["q"] for q in questions]), c_local, questions, chunks
    )
    if os.environ.get("OPENAI_API_KEY"):
        import openai

        client = openai.OpenAI()
        model = "text-embedding-3-small"

        def remote(items: list[str]) -> np.ndarray:
            data = client.embeddings.create(model=model, input=items).data
            return np.array([d.embedding for d in data])

        result["openai_" + model] = recall(
            remote([q["q"] for q in questions]), remote(texts), questions, chunks
        )
    else:
        result["openai_text-embedding-3-small"] = "dilewati: OPENAI_API_KEY kosong"
    save("quality", result)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("throughput")
    p.add_argument("--batches", type=int, default=2, help="jumlah batch diukur per kombinasi")
    p.add_argument("--max-batch-tokens", type=int, default=32768)
    p = sub.add_parser("latency")
    p.add_argument("--budgets", type=int, nargs="+", default=[2048, 4096])
    p.add_argument("--bulk-chunks", type=int, default=96)
    p.add_argument("--bulk-tokens", type=int, default=500)
    p.add_argument("--probe-interval", type=float, default=2.0)
    sub.add_parser("quality")
    args = ap.parse_args()
    asyncio.run({"throughput": throughput, "latency": latency, "quality": quality}[args.cmd](args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
