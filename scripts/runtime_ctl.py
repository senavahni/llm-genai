"""Hentikan Local Runtime dengan rapi (dipanggil stop-all.bat).

    python scripts\\runtime_ctl.py shutdown [--wait 15]

POST /runtime/shutdown (header X-Runtime-Token = RUNTIME_TOKEN): runtime meng-unload semua
model, mencatat event `runtime_stop`, lalu keluar dengan kode 0 (supervisor tidak me-restart).
Exit 0 bila port runtime sudah tertutup dalam --wait detik, 1 bila belum (pakai taskkill)."""

import argparse
import os
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from scripts.healthcheck import _token_from_env  # noqa: E402


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Kontrol Local Runtime")
    parser.add_argument("command", choices=["shutdown"])
    parser.add_argument("--wait", type=float, default=15)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("RUNTIME_PORT", 8100)))
    args = parser.parse_args()

    if not port_open(args.host, args.port):
        print("runtime tidak berjalan")
        return 0
    token = _token_from_env("RUNTIME_TOKEN") or ""
    try:
        r = httpx.post(
            f"http://{args.host}:{args.port}/runtime/shutdown",
            headers={"X-Runtime-Token": token},
            timeout=10,
        )
        print(f"shutdown: HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        print(f"shutdown gagal: {exc}", file=sys.stderr)
    deadline = time.monotonic() + args.wait
    while time.monotonic() < deadline:
        if not port_open(args.host, args.port):
            print("runtime berhenti")
            return 0
        time.sleep(0.5)
    print(f"runtime masih hidup setelah {args.wait:g} detik", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
