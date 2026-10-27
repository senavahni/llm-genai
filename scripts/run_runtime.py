"""Entry point Local Runtime (dipanggil scripts\\start-runtime.bat)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app.core.config import ConfigError, get_settings  # noqa: E402
from runtime.core.settings import runtime_bind_host  # noqa: E402


def main() -> int:
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    host = runtime_bind_host(settings)
    if host != settings.runtime_host:
        print(
            f"RUNTIME_HOST={settings.runtime_host} diabaikan: runtime selalu bind {host}",
            file=sys.stderr,
        )
    uvicorn.run(
        "runtime.main:app",
        host=host,
        port=settings.runtime_port,
        workers=1,
        log_config=None,  # logging diatur setup_logging(component="runtime")
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
