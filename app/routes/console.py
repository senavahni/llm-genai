"""Admin Console (`/console`): halaman statis pengelola kredensial, hanya dari localhost.

Halaman tidak memuat data apa pun; semua data diambil lewat Admin API (`/admin/*`) memakai admin
key yang diketik operator dan disimpan di memori tab saja. Guard di sini lapis tambahan: koneksi
harus dari loopback (peer socket, bukan X-Forwarded-For) dengan Host lokal (anti DNS rebinding).
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

CONSOLE_DIR = Path(__file__).resolve().parents[1] / "console"
ASSETS = {
    "console.js": "text/javascript",
    "console.css": "text/css",
    "kit.js": "text/javascript",
    "usage-charts.js": "text/javascript",
}
LOOPBACK_PEERS = {"127.0.0.1", "::1"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

router = APIRouter(include_in_schema=False)


def _hostname(host_header: str) -> str:
    if host_header.startswith("["):
        return host_header.split("]", 1)[0] + "]"
    return host_header.rsplit(":", 1)[0]


def is_local_request(request: Request) -> bool:
    peer = request.client.host if request.client else None
    return peer in LOOPBACK_PEERS and _hostname(request.headers.get("host", "")) in LOCAL_HOSTS


def _forbidden() -> Response:
    return PlainTextResponse(
        "Admin Console hanya bisa dibuka dari komputer ini (http://127.0.0.1).",
        status_code=403,
        headers=SECURITY_HEADERS,
    )


@router.get("/console")
async def console_page(request: Request) -> Response:
    if not is_local_request(request):
        return _forbidden()
    return FileResponse(
        CONSOLE_DIR / "index.html", media_type="text/html", headers=SECURITY_HEADERS
    )


@router.get("/console/{name}")
async def console_asset(name: str, request: Request) -> Response:
    if not is_local_request(request):
        return _forbidden()
    media_type = ASSETS.get(name)
    if media_type is None:
        return PlainTextResponse("not found", status_code=404, headers=SECURITY_HEADERS)
    return FileResponse(CONSOLE_DIR / name, media_type=media_type, headers=SECURITY_HEADERS)
