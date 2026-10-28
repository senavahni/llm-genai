"""Tunggu sampai URL health merespons 200 (dipakai start-all.bat).

    python scripts\\healthcheck.py http://127.0.0.1:8100/health/ready 900 --token-env RUNTIME_TOKEN
    python scripts\\healthcheck.py http://127.0.0.1:8000/health/ready 60

Exit 0 bila siap sebelum batas waktu, 1 bila tidak. Progres (mis. `loaded 1/2` saat compile NPU
pertama) dicetak tiap ±15 detik."""

import argparse
import json
import os
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _token_from_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    # env.bat memuat .env; fallback baca .env langsung bila dijalankan tanpa env.bat
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):  # noqa: SIM115
            key, sep, val = line.strip().partition("=")
            if sep and key.strip() == name:
                return val.strip().strip('"')
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("timeout", type=float, nargs="?", default=60)
    ap.add_argument("--token-env", help="nama env berisi token (header X-Runtime-Token)")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    headers = {}
    if args.token_env:
        token = _token_from_env(args.token_env)
        if not token:
            print(f"env {args.token_env} kosong", file=sys.stderr)
            return 1
        headers["X-Runtime-Token"] = token
    deadline = time.monotonic() + args.timeout
    last_print = 0.0
    detail = "belum ada respons"
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(args.url, headers=headers, timeout=5)
            if resp.status_code == 200:
                print(f"siap: {args.url}")
                return 0
            try:
                body = resp.json()
                detail = (
                    f"HTTP {resp.status_code} {body.get('status')} {body.get('progress') or ''}"
                )
            except json.JSONDecodeError:
                detail = f"HTTP {resp.status_code}"
        except httpx.HTTPError as exc:
            detail = type(exc).__name__
        if time.monotonic() - last_print > 15:
            remaining = int(deadline - time.monotonic())
            print(f"menunggu {args.url}: {detail} (sisa {remaining} s)", flush=True)
            last_print = time.monotonic()
        time.sleep(args.interval)
    print(f"TIDAK SIAP setelah {args.timeout:g} s: {args.url} ({detail})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
