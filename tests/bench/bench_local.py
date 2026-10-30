"""Benchmark model lokal lewat gateway (TASK-20, NF11). Gateway + runtime harus berjalan.

    set LGW_TEST_KEY=lgw_...
    scripts\\bench.bat [--runs 3] [--fim-runs 20] [--only local/qwen2.5-7b]

Mengukur: FIM TTFT p50/p95 & token/s; chat TTFT & token/s (prompt ±1k token, output 256) plus
waktu load/swap (requests.load_ms); VL juga TTFT dengan gambar; SD detik/gambar 512² (25 step).
Hasil mentah → logs/bench-results.json; tabel → docs/perf-report.md di antara penanda
<!-- bench:start --> / <!-- bench:end -->."""

import argparse
import asyncio
import base64
import io
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts._seedfile import load_seed, local_models  # noqa: E402

BASE_URL = os.environ.get("LGW_BASE_URL", "http://127.0.0.1:8000")
RESULTS = ROOT / "logs" / "bench-results.json"
REPORT = ROOT / "docs" / "perf-report.md"
START, END = "<!-- bench:start -->", "<!-- bench:end -->"

PARAGRAPH = (
    "Gateway LLM ini meneruskan permintaan dari agen ke provider remote atau runtime lokal "
    "yang menjalankan model di iGPU dan NPU Intel, mencatat pemakaian token, biaya, dan "
    "latensi setiap permintaan ke PostgreSQL agar laporan harian dapat dibuat. "
)
LONG_PROMPT = PARAGRAPH * 22 + "\n\nTulis esai panjang dan rinci tentang arsitektur di atas."
FIM_PREFIX = 'def is_prime(n: int) -> bool:\n    """True bila n bilangan prima."""\n'
FIM_SUFFIX = "\n\nprint(is_prime(7))\n"


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def png_data_url() -> str:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (448, 448), "white")
    ImageDraw.Draw(img).rectangle([40, 40, 200, 400], fill="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def stream_timed(client: httpx.AsyncClient, path: str, body: dict) -> dict[str, Any]:
    """TTFT (detik sampai token teks pertama), token/s dekode, usage, request id."""
    body = {**body, "stream": True, "stream_options": {"include_usage": True}}
    t0 = time.perf_counter()
    first = last = None
    usage: dict[str, int] = {}
    async with client.stream("POST", path, json=body) as r:
        if r.status_code != 200:
            raise RuntimeError(f"{path} {r.status_code}: {(await r.aread())[:300]!r}")
        request_id = r.headers["x-request-id"]
        async for line in r.aiter_lines():
            if not line.startswith("data: {"):
                continue
            chunk = json.loads(line[6:])
            if chunk.get("usage"):
                usage = chunk["usage"]
            for choice in chunk.get("choices") or []:
                piece = choice.get("text") or (choice.get("delta") or {}).get("content")
                if piece:
                    now = time.perf_counter()
                    first = first or now
                    last = now
    assert first and last, "tidak ada token"
    gen = usage.get("completion_tokens", 0)
    decode_s = last - first
    return {
        "request_id": request_id,
        "ttft_s": first - t0,
        "total_s": last - t0,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": gen,
        "tok_per_s": (gen - 1) / decode_s if gen > 1 and decode_s > 0 else None,
    }


async def load_ms(request_ids: list[str]) -> dict[str, int | None]:
    """load_ms/queue_ms dari tabel requests (DB dev) — ditulis async oleh finisher usage."""
    import asyncpg
    from dotenv import dotenv_values

    await asyncio.sleep(2)
    url = (dotenv_values(ROOT / ".env").get("DATABASE_URL") or "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT id::text, load_ms, device FROM requests WHERE id = ANY($1::uuid[])",
            request_ids,
        )
    finally:
        await conn.close()
    found = {r["id"]: r for r in rows}
    if any(r["device"] == "cpu" for r in rows):
        raise RuntimeError("request lokal berjalan di CPU (NF9 dilanggar)")
    return {rid: (found[rid]["load_ms"] if rid in found else None) for rid in request_ids}


async def bench_fim(client: httpx.AsyncClient, alias: str, runs: int) -> dict[str, Any]:
    body = {
        "model": alias,
        "prompt": FIM_PREFIX,
        "suffix": FIM_SUFFIX,
        "max_tokens": 48,
        "temperature": 0,
    }
    await stream_timed(client, "/v1/completions", body)  # pemanasan
    samples = [await stream_timed(client, "/v1/completions", body) for _ in range(runs)]
    ttfts = [s["ttft_s"] * 1000 for s in samples]
    rates = [s["tok_per_s"] for s in samples if s["tok_per_s"]]
    return {
        "kind": "fim",
        "alias": alias,
        "runs": runs,
        "ttft_p50_ms": round(statistics.median(ttfts)),
        "ttft_p95_ms": round(pct(ttfts, 95)),
        "tok_per_s": round(statistics.median(rates), 1) if rates else None,
    }


async def bench_chat(
    client: httpx.AsyncClient, alias: str, other: str | None, runs: int, vision: bool
) -> dict[str, Any]:
    content: Any = LONG_PROMPT
    if vision:
        content = [
            {
                "type": "text",
                "text": "Describe this image in detail, then write a long "
                "essay about the color red.",
            },
            {"type": "image_url", "image_url": {"url": png_data_url()}},
        ]
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 256,
        "temperature": 0,
    }
    samples = []
    swap_note = None
    for i in range(runs):
        if other:  # muat model lain dulu → request berikut memaksa swap
            try:
                await stream_timed(
                    client,
                    "/v1/chat/completions",
                    {
                        "model": other,
                        "messages": [{"role": "user", "content": "hai"}],
                        "max_tokens": 2,
                    },
                )
            except RuntimeError as exc:
                swap_note = f"swap dilewati: {other} gagal dimuat ({str(exc)[:80]})"
                print(f"  {swap_note}", flush=True)
                other = None
        # awalan unik per run: tanpa ini run berikutnya memakai prefix cache (TTFT ±0,2 s)
        unique = {
            **body,
            "messages": [
                {"role": "system", "content": f"Sesi #{i}-{time.time()}"},
                *body["messages"],
            ],
        }
        sample = await stream_timed(client, "/v1/chat/completions", unique)
        samples.append(sample)
        print(
            f"  {alias} run {i + 1}/{runs}: TTFT {sample['ttft_s']:.1f} s, "
            f"{sample['tok_per_s'] or 0:.1f} tok/s",
            flush=True,
        )
    loads = await load_ms([s["request_id"] for s in samples])
    # TTFT bersih = TTFT - waktu load model (load/swap dilaporkan terpisah)
    net = [s["ttft_s"] - (loads.get(s["request_id"]) or 0) / 1000 for s in samples]
    load_values = [v for v in loads.values() if v]
    return {
        "kind": "vision" if vision else "chat",
        "alias": alias,
        "runs": runs,
        "prompt_tokens": samples[0]["prompt_tokens"],
        "completion_tokens": round(statistics.median(s["completion_tokens"] for s in samples)),
        "ttft_s": round(statistics.median(net), 2),
        "tok_per_s": round(statistics.median(s["tok_per_s"] for s in samples if s["tok_per_s"]), 1),
        "swap_load_ms": round(statistics.median(load_values)) if load_values else None,
        "note": swap_note,
    }


async def bench_image(client: httpx.AsyncClient, alias: str, runs: int) -> dict[str, Any]:
    body = {
        "model": alias,
        "prompt": "a red house near a lake, photo",
        "size": "512x512",
        "n": 1,
        "steps": 25,
        "response_format": "b64_json",
    }
    times = []
    for i in range(runs):
        t0 = time.perf_counter()
        r = await client.post("/v1/images/generations", json={**body, "seed": i})
        r.raise_for_status()
        times.append(time.perf_counter() - t0)
        print(f"  {alias} run {i + 1}/{runs}: {times[-1]:.1f} s", flush=True)
    return {
        "kind": "image",
        "alias": alias,
        "runs": runs,
        "s_per_image": round(statistics.median(times), 1),
        "min_s": round(min(times), 1),
    }


def render(results: list[dict[str, Any]], measured_at: str) -> str:
    lines = [START, f"_Diukur {measured_at} lewat gateway (`tests/bench/bench_local.py`)._", ""]
    fim = [r for r in results if r["kind"] == "fim"]
    if fim:
        lines += ["| Model (FIM) | TTFT p50 | TTFT p95 | token/s | runs |", "|---|---|---|---|---|"]
        lines += [
            f"| {r['alias']} | {r['ttft_p50_ms']} ms | {r['ttft_p95_ms']} ms | "
            f"{r['tok_per_s']} | {r['runs']} |"
            for r in fim
        ]
        lines.append("")
    chat = [r for r in results if r["kind"] in ("chat", "vision")]
    if chat:
        lines += [
            "| Model (chat) | prompt tok | output tok | TTFT (tanpa load) | token/s | load model |",
            "|---|---|---|---|---|---|",
        ]
        for r in chat:
            swap = f"{r['swap_load_ms'] / 1000:.1f} s" if r["swap_load_ms"] else "-"
            name = r["alias"] + (" (+gambar)" if r["kind"] == "vision" else "")
            lines.append(
                f"| {name} | {r['prompt_tokens']} | {r['completion_tokens']} | "
                f"{r['ttft_s']} s | {r['tok_per_s']} | {swap} |"
            )
        lines.append("")
    image = [r for r in results if r["kind"] == "image"]
    if image:
        lines += [
            "| Model (gambar) | detik/gambar 512², 25 step (median) | tercepat | runs |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {r['alias']} | {r['s_per_image']} s | {r['min_s']} s | {r['runs']} |" for r in image
        ]
        lines.append("")
    errors = [r for r in results if r["kind"] == "error"]
    if errors:
        lines += ["| Model gagal diukur | Error |", "|---|---|"]
        lines += [
            f"| {r['alias']} | {r['error'][:160].replace(chr(10), ' ').replace('|', '/')} |"
            for r in errors
        ]
        lines.append("")
    notes = [f"- {r['alias']}: {r['note']}" for r in results if r.get("note")]
    if notes:
        lines += [*notes, ""]
    lines.append(END)
    return "\n".join(lines)


def write_report(block: str) -> None:
    text = REPORT.read_text(encoding="utf-8") if REPORT.exists() else f"{START}\n{END}\n"
    head, _, rest = text.partition(START)
    _, _, tail = rest.partition(END)
    REPORT.write_text(head + block + tail, encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--fim-runs", type=int, default=20)
    parser.add_argument("--image-runs", type=int, default=3)
    parser.add_argument("--only", action="append", help="alias tertentu (boleh berulang)")
    parser.add_argument("--no-report", action="store_true", help="jangan ubah perf-report.md")
    parser.add_argument(
        "--merge", action="store_true", help="gabung dengan logs/bench-results.json (per alias)"
    )
    parser.add_argument(
        "--no-swap", action="store_true", help="jangan paksa swap model GPU sebelum tiap run"
    )
    args = parser.parse_args()
    key = os.environ.get("LGW_TEST_KEY")
    if not key:
        print("set LGW_TEST_KEY (key client dengan akses local/*)", file=sys.stderr)
        return 2

    catalog = [m for m in local_models(load_seed()) if not args.only or m["alias"] in args.only]
    gpu_chat = [
        m["alias"]
        for m in local_models(load_seed())
        if m["device"] == "gpu" and m["model_type"] == "chat"
    ]
    results = []
    async with httpx.AsyncClient(
        base_url=BASE_URL, timeout=1800, headers={"Authorization": f"Bearer {key}"}
    ) as client:
        for m in catalog:
            alias = m["alias"]
            print(f"[bench] {alias}", flush=True)
            try:
                if m["model_type"] == "completion":
                    results.append(await bench_fim(client, alias, args.fim_runs))
                elif m["model_type"] == "image":
                    results.append(await bench_image(client, alias, args.image_runs))
                else:
                    # model GPU lain yang tidak muat bersamaan → swap tiap run
                    other = (
                        None if args.no_swap else next((a for a in gpu_chat if a != alias), None)
                    )
                    results.append(
                        await bench_chat(
                            client, alias, other, args.runs, bool(m.get("supports_vision"))
                        )
                    )
            except (RuntimeError, httpx.HTTPError) as exc:  # dicatat, model lain tetap diukur
                results.append({"kind": "error", "alias": alias, "error": str(exc)[:300]})
            print(f"  → {results[-1]}", flush=True)

    if args.merge and RESULTS.exists():
        fresh = {r["alias"] for r in results}
        previous = json.loads(RESULTS.read_text(encoding="utf-8"))["results"]
        results = [r for r in previous if r["alias"] not in fresh] + results
    measured_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    RESULTS.write_text(
        json.dumps({"measured_at": measured_at, "results": results}, indent=2), encoding="utf-8"
    )
    if not args.no_report:
        write_report(render(results, measured_at))
    print(render(results, measured_at))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
