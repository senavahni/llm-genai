"""Gateway dengan provider palsu di PROSES TERPISAH untuk load test (DB llm_gateway_test).

    python -m tests.load.fake_gateway --port 8765 --ready-file key.txt [--delay 0.02 --chunks 25]

Tabel DB uji dikosongkan & di-seed, project `agent-a` dibuat, lalu full key ditulis ke
--ready-file sebagai tanda server siap. Limit RPM/TPM default dinaikkan (yang diukur overhead)."""

import argparse
import asyncio
import os
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_RPM_LIMIT", "10000000")
os.environ.setdefault("DEFAULT_TPM_LIMIT", "1000000000000")

import tests.conftest as base  # noqa: E402  (set env DB uji sebelum modul app dipakai)


async def main(args: argparse.Namespace) -> None:
    import uvicorn
    from sqlalchemy import text

    from app.core import database
    from app.core.config import get_settings
    from app.utils.logger import setup_logging, shutdown_logging
    from app.utils.streaming import drain_finishers
    from tests.integration.conftest import (
        FAKE_PROVIDER_ENV,
        build_fake_gateway,
        default_project_keys,
    )

    settings = get_settings()
    settings.storage_dir = tempfile.mkdtemp(prefix="lgw-load-")
    settings.log_dir = str(Path(args.ready_file).parent / "logs")
    # seperti produksi: log JSON ke file lewat QueueHandler (lifespan dimatikan di sini)
    setup_logging(settings.model_copy(update={"app_env": "prod"}), console=False)
    for env in FAKE_PROVIDER_ENV:
        os.environ[env] = "fake-test-key"
    database.configure_db()
    async with database.get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {base._ALL_TABLES} RESTART IDENTITY CASCADE"))

    app, providers = await build_fake_gateway()
    for provider in providers.values():
        if args.delay:
            provider.mode, provider.delay_s = "slow", args.delay
        provider.chunks = [f"t{i} " for i in range(args.chunks)]
    key, _ = await default_project_keys()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.port,
        lifespan="off",
        log_level="warning",
        access_log=False,
        backlog=4096,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    Path(args.ready_file).write_text(key, encoding="utf-8")
    try:
        await task
    finally:
        await drain_finishers()
        await database.dispose_db()
        shutdown_logging()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ready-file", required=True)
    parser.add_argument("--delay", type=float, default=0.0, help="detik per chunk (mode slow)")
    parser.add_argument("--chunks", type=int, default=3)
    asyncio.run(main(parser.parse_args()))
