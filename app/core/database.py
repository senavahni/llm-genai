"""Engine & session async. Engine dibuat saat init_db() (bukan saat import) agar modul ini bisa
diimpor tanpa konfigurasi lengkap (mis. oleh test atau script)."""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def configure_db(settings: Settings | None = None) -> AsyncEngine:
    """Buat engine + sessionmaker global (idempoten)."""
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_engine(settings or get_settings())
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    return configure_db()


def SessionLocal() -> AsyncSession:  # noqa: N802 - nama mengikuti konvensi SQLAlchemy
    """Session baru. Untuk background task (log/usage) selalu pakai ini, bukan session request."""
    configure_db()
    assert _sessionmaker is not None
    return _sessionmaker()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def ping_db() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("db_ping_failed", error=str(exc))
        return False


async def init_db(settings: Settings | None = None) -> None:
    configure_db(settings)
    if await ping_db():
        log.info("db_connected")
    else:
        # Tidak fatal: /health/ready akan 503 dan pool_pre_ping menyambung ulang saat DB naik.
        log.error("db_unreachable_at_startup")


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
