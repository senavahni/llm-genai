"""Runtime memakai Settings yang sama dengan gateway (app/core/config.py)."""

from app.core.config import Settings, get_settings

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def runtime_bind_host(settings: Settings) -> str:
    """Runtime SELALU bind loopback (PRD §11.5), apa pun isi RUNTIME_HOST."""
    return settings.runtime_host if settings.runtime_host in LOOPBACK_HOSTS else "127.0.0.1"


def device_budgets(settings: Settings) -> dict[str, int]:
    return {"gpu": settings.gpu_budget_mb, "npu": settings.npu_budget_mb}


__all__ = ["Settings", "device_budgets", "get_settings", "runtime_bind_host"]
