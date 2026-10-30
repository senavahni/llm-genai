"""Jalankan app ASGI di server uvicorn sungguhan (port acak, loop yang sama dengan test) untuk
contract test: SSE, header, dan koneksi TCP diuji lewat jaringan, bukan ASGITransport."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn


@asynccontextmanager
async def serve(app: Any) -> AsyncIterator[str]:
    """Yield base URL `http://127.0.0.1:<port>`. Lifespan dimatikan: state app (registry palsu)
    sudah disiapkan fixture."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, lifespan="off", log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()  # lempar error startup
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
