"""Fixture bersama. Test integrasi memakai database terpisah `llm_gateway_test` (kredensial sama
dengan DATABASE_URL di .env, atau override lewat TEST_DATABASE_URL)."""

import os
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
_dotenv = dotenv_values(ROOT / ".env")


def _test_database_url() -> str:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    base = _dotenv.get("DATABASE_URL") or "postgresql+asyncpg://llm_gateway:x@127.0.0.1:5432/x"
    parts = urlsplit(base)
    return urlunsplit(parts._replace(path="/llm_gateway_test"))


TEST_DATABASE_URL = _test_database_url()
TEST_PEPPER = "test-pepper-" + "x" * 40
TEST_RUNTIME_TOKEN = "test-runtime-token-" + "y" * 40

# Harus di-set sebelum modul app memanggil get_settings().
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DATABASE_URL,
        "GATEWAY_KEY_PEPPER": TEST_PEPPER,
        "RUNTIME_TOKEN": TEST_RUNTIME_TOKEN,
        "LOG_LEVEL": "INFO",
    }
)

from app.core import database  # noqa: E402
from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--hardware",
        action="store_true",
        help="jalankan test hardware (@pytest.mark.gpu / npu) dengan model nyata di local_models/",
    )
    parser.addoption(
        "--live", action="store_true", help="jalankan test provider asli (@pytest.mark.live)"
    )
    parser.addoption(
        "--load", action="store_true", help="jalankan load test (@pytest.mark.load, menit-an)"
    )


# marker -> opsi CLI yang mengaktifkannya; tanpa opsi, test dengan marker tsb di-skip
_OPT_IN = {"gpu": "--hardware", "npu": "--hardware", "live": "--live", "load": "--load"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        for marker, option in _OPT_IN.items():
            if marker in item.keywords and not config.getoption(option):
                item.add_marker(pytest.mark.skip(reason=f"jalankan dengan {option}"))
                break


def _db_reachable() -> bool:
    parts = urlsplit(TEST_DATABASE_URL)
    try:
        with socket.create_connection((parts.hostname or "127.0.0.1", parts.port or 5432), 1):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    """downgrade base → upgrade head pada DB test (sekaligus menguji migrasi bolak-balik)."""
    if not _db_reachable():
        pytest.skip("PostgreSQL tidak berjalan (jalankan scripts\\start-postgres.bat)")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL


_ALL_TABLES = (
    "audit_logs, usage_daily, runtime_events, generated_images, request_payloads, "
    "request_attempts, requests, quotas, project_allowed_models, model_route_targets, "
    "model_routes, models, providers, api_keys, projects"
)


@pytest.fixture
async def db(migrated_db: str) -> AsyncIterator[None]:
    """DB bersih per test."""
    from sqlalchemy import text

    from app.services.key_service import key_service

    database.configure_db()
    async with database.get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))
    key_service.invalidate()
    yield
    await key_service.drain()


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engine() -> AsyncIterator[None]:
    yield
    await database.dispose_db()
