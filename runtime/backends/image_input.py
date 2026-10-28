"""Input gambar untuk model vision (TASK-11): data URL base64 atau URL http(s) dengan proteksi
SSRF, batas ukuran & waktu, lalu resize agar sisi terpanjang ≤ `max_px`."""

import asyncio
import base64
import binascii
import io
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
import numpy as np

from app.utils.errors import InvalidRequestError, PayloadTooLarge

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT_S = 10.0
MAX_REDIRECTS = 3


def _decode_data_url(url: str) -> bytes:
    header, _, data = url.partition(",")
    if ";base64" not in header:
        raise InvalidRequestError("Data URL gambar harus base64", param="image_url")
    if len(data) * 3 // 4 > MAX_IMAGE_BYTES:
        raise PayloadTooLarge("Gambar maksimal 10 MB", param="image_url")
    try:
        return base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidRequestError("Data URL gambar bukan base64 valid", param="image_url") from exc


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def _check_host(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise InvalidRequestError("URL gambar harus http(s) atau data URL", param="image_url")
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo, parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise InvalidRequestError(f"Host gambar tidak dikenal: {parts.hostname}") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses or not all(_is_public(a) for a in addresses):
        # anti-SSRF: runtime tidak boleh dipakai menjangkau jaringan internal/loopback/metadata
        raise InvalidRequestError(
            "URL gambar menunjuk alamat privat/internal; ditolak", param="image_url"
        )


async def fetch_url(url: str, client: httpx.AsyncClient | None = None) -> bytes:
    own = client is None
    http = client or httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, follow_redirects=False)
    try:
        async with asyncio.timeout(FETCH_TIMEOUT_S):
            for _ in range(MAX_REDIRECTS + 1):
                await _check_host(url)  # tiap hop redirect diperiksa ulang
                async with http.stream("GET", url) as resp:
                    if resp.is_redirect and resp.headers.get("location"):
                        url = urljoin(url, resp.headers["location"])
                        continue
                    if resp.status_code != 200:
                        raise InvalidRequestError(
                            f"Gagal mengunduh gambar: HTTP {resp.status_code}", param="image_url"
                        )
                    declared = int(resp.headers.get("content-length") or 0)
                    if declared > MAX_IMAGE_BYTES:
                        raise PayloadTooLarge("Gambar maksimal 10 MB", param="image_url")
                    chunks, size = [], 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise PayloadTooLarge("Gambar maksimal 10 MB", param="image_url")
                        chunks.append(chunk)
                    return b"".join(chunks)
            raise InvalidRequestError("Terlalu banyak redirect URL gambar", param="image_url")
    except TimeoutError as exc:
        raise InvalidRequestError("Unduh gambar > 10 detik", param="image_url") from exc
    except httpx.HTTPError as exc:
        raise InvalidRequestError(
            f"Gagal mengunduh gambar: {type(exc).__name__}", param="image_url"
        ) from exc
    finally:
        if own:
            await http.aclose()


def decode_image(raw: bytes, max_px: int) -> np.ndarray:
    """Bytes gambar → array uint8 [H, W, 3], sisi terpanjang ≤ max_px."""
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidRequestError("Konten bukan gambar valid", param="image_url") from exc
    rgb = img.convert("RGB")
    if max(rgb.size) > max_px:
        rgb.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    return np.asarray(rgb, dtype=np.uint8)


async def load_image(url: str, max_px: int, client: httpx.AsyncClient | None = None) -> np.ndarray:
    raw = _decode_data_url(url) if url.startswith("data:") else await fetch_url(url, client)
    return await asyncio.to_thread(decode_image, raw, max_px)
