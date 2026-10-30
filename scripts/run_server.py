"""Entry point gateway (dipanggil scripts\\start-gateway.bat).

    python scripts\\run_server.py                 :: 127.0.0.1:APP_PORT (APP_HOST dari .env)
    python scripts\\run_server.py --lan           :: bind 0.0.0.0 (akses LAN, Mode A)
    python scripts\\run_server.py --behind-proxy  :: percaya X-Forwarded-* dari Traefik lokal
    python scripts\\run_server.py --reload        :: dev: restart otomatis saat app/ berubah

Selalu 1 worker: rate limiter, kuota berjalan, dan circuit breaker disimpan in-memory."""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app.core.config import ConfigError, get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Jalankan gateway LLM (uvicorn, 1 worker)")
    parser.add_argument("--lan", action="store_true", help="bind 0.0.0.0")
    parser.add_argument("--behind-proxy", action="store_true", help="di belakang Traefik lokal")
    parser.add_argument("--reload", action="store_true", help="mode dev (auto-reload)")
    args = parser.parse_args()
    if args.behind_proxy:
        # IP klien & URL publik dari X-Forwarded-* (Traefik); diwarisi proses reload juga
        os.environ["TRUST_PROXY"] = "true"
    try:
        settings = get_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.lan and args.behind_proxy:
        print("--lan tidak perlu di belakang proxy: Traefik yang membuka port LAN", file=sys.stderr)
        return 2
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0" if args.lan else settings.app_host,  # noqa: S104 (opsi eksplisit)
        port=settings.app_port,
        workers=1,
        reload=args.reload,
        reload_dirs=[str(ROOT / "app")] if args.reload else None,
        timeout_keep_alive=75,
        access_log=False,  # diganti access log middleware (logs\access.log)
        log_config=None,  # logging diatur setup_logging() di lifespan
        proxy_headers=args.behind_proxy,
        forwarded_allow_ips="127.0.0.1" if args.behind_proxy else None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
