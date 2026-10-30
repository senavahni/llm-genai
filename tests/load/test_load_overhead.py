"""Load test overhead gateway (TASK-20, NF1/NF2) terhadap provider palsu lewat HTTP sungguhan.

    scripts\\test.bat tests\\load --load -s            :: durasi default (A 120 dtk, B 30 dtk)
    set LOAD_DURATION_S=20 & scripts\\test.bat tests\\load --load -s

Gateway berjalan di proses terpisah (tests/load/fake_gateway.py, 1 worker uvicorn) dengan
pencatatan usage ke PostgreSQL seperti produksi; generator beban di proses pytest. Hasil ditulis
ke logs/load-results.json dan dirangkum di docs/perf-report.md.
"""

import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.load]

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "logs" / "load-results.json"
BODY = {"model": "smart", "messages": [{"role": "user", "content": "halo"}]}


def _duration(default: float) -> float:
    return float(os.environ.get("LOAD_DURATION_S", default))


def _pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def _save(name: str, result: dict) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    data[name] = result
    RESULTS.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n{name}: {json.dumps(result)}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def fake_gateway(tmp_path: Path, *extra: str) -> AsyncIterator[httpx.AsyncClient]:
    port, ready = _free_port(), tmp_path / "ready.txt"
    log = (tmp_path / "server.out").open("wb")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.load.fake_gateway",
            "--port",
            str(port),
            "--ready-file",
            str(ready),
            *extra,
        ],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 60
        while not ready.exists():
            if proc.poll() is not None or time.monotonic() > deadline:
                log.flush()
                pytest.fail((tmp_path / "server.out").read_text(errors="replace")[-3000:])
            await asyncio.sleep(0.1)
        key = ready.read_text(encoding="utf-8")
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
            limits=httpx.Limits(max_connections=1000, max_keepalive_connections=1000),
        ) as client:
            for _ in range(20):  # pemanasan koneksi & cache key/route
                await client.post("/v1/chat/completions", json=BODY)
            yield client
    finally:
        proc.terminate()
        proc.wait(30)
        log.close()


async def _open_loop(client: httpx.AsyncClient, rps: int, duration: float) -> dict:
    total = int(rps * duration)
    latencies: list[float] = []
    errors: list[str] = []

    async def one() -> None:
        t0 = time.perf_counter()
        try:
            r = await client.post("/v1/chat/completions", json=BODY)
        except httpx.HTTPError as exc:
            errors.append(type(exc).__name__)
            return
        if r.status_code == 200:
            latencies.append((time.perf_counter() - t0) * 1000)
        else:
            errors.append(str(r.status_code))

    start = time.perf_counter()
    tasks = []
    for i in range(total):  # open-loop: jadwal tetap, tidak menunggu respons
        delay = start + i / rps - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(one()))
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start
    return {
        "target_rps": rps,
        "achieved_rps": round(total / elapsed, 1),
        "requests": total,
        "errors": len(errors),
        "error_kinds": sorted(set(errors)),
        "p50_ms": round(_pct(latencies, 50), 1),
        "p95_ms": round(_pct(latencies, 95), 1),
        "p99_ms": round(_pct(latencies, 99), 1),
        "mean_ms": round(statistics.fmean(latencies), 1) if latencies else None,
    }


async def test_scenario_b_non_stream_steps(migrated_db, tmp_path):
    """Skenario B: non-stream bertahap (default 25/50/100/200 RPS, env LOAD_RPS_STEPS), provider
    tanpa latensi → latensi = overhead gateway. Langkah pertama wajib bebas error & p95 < 30 ms;
    langkah lain dicatat untuk mencari titik jenuh (lihat docs/perf-report.md)."""
    steps = [int(x) for x in os.environ.get("LOAD_RPS_STEPS", "25,50,100,200").split(",")]
    duration = _duration(30)
    results = []
    async with fake_gateway(tmp_path) as client:
        for rps in steps:
            results.append(await _open_loop(client, rps, duration))
            await asyncio.sleep(3)  # biarkan finisher usage menyelesaikan antrean
    _save("scenario_b", {"duration_s": duration, "steps": results})
    first = results[0]
    assert first["errors"] == 0 and first["p95_ms"] < 30, first


async def test_scenario_a_50_concurrent_streams(migrated_db, tmp_path):
    """Skenario A: 50 stream bersamaan, provider 20 ms/chunk × 25 chunk (≈500 ms/stream)."""
    chunks, delay = 25, 0.02
    floor_ms = chunks * delay * 1000  # durasi stream murni dari provider
    concurrency, duration = 50, _duration(120)
    ttft_overhead: list[float] = []
    total_overhead: list[float] = []
    errors: list[str] = []

    async with fake_gateway(tmp_path, "--delay", str(delay), "--chunks", str(chunks)) as client:
        stop_at = time.perf_counter() + duration

        async def worker() -> None:
            body = {**BODY, "stream": True}
            while time.perf_counter() < stop_at:
                t0 = time.perf_counter()
                first = None
                try:
                    async with client.stream("POST", "/v1/chat/completions", json=body) as r:
                        if r.status_code != 200:
                            errors.append(str(r.status_code))
                            await r.aread()
                            continue
                        async for line in r.aiter_lines():
                            if first is None and line.startswith("data: {"):
                                first = time.perf_counter()
                            if line == "data: [DONE]":
                                break
                except httpx.HTTPError as exc:
                    errors.append(type(exc).__name__)
                    continue
                end = time.perf_counter()
                if first is None:
                    errors.append("no_chunk")
                    continue
                ttft_overhead.append((first - t0) * 1000 - delay * 1000)
                total_overhead.append((end - t0) * 1000 - floor_ms)

        await asyncio.gather(*(worker() for _ in range(concurrency)))

    result = {
        "concurrency": concurrency,
        "duration_s": duration,
        "streams": len(total_overhead),
        "errors": len(errors),
        "ttft_overhead_p50_ms": round(_pct(ttft_overhead, 50), 1),
        "ttft_overhead_p95_ms": round(_pct(ttft_overhead, 95), 1),
        "stream_overhead_p50_ms": round(_pct(total_overhead, 50), 1),
        "stream_overhead_p95_ms": round(_pct(total_overhead, 95), 1),
    }
    _save("scenario_a", result)
    assert not errors, sorted(set(errors))
