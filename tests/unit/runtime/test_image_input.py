import base64
import io
import socket

import httpx
import pytest
import respx
from PIL import Image

from app.utils.errors import InvalidRequestError, PayloadTooLarge
from runtime.backends import image_input
from runtime.backends.image_input import load_image


def _png(size=(40, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "blue").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def dns(monkeypatch):
    table = {"img.example.com": "93.184.216.34", "evil.example.com": "10.0.0.5"}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror("unknown")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table[host], port))]

    monkeypatch.setattr(image_input.socket, "getaddrinfo", fake_getaddrinfo)
    return table


async def test_data_url_decoded_and_resized():
    url = "data:image/png;base64," + base64.b64encode(_png((3000, 1500))).decode()
    arr = await load_image(url, max_px=1280)
    assert arr.shape == (640, 1280, 3)
    small = await load_image("data:image/png;base64," + base64.b64encode(_png()).decode(), 1280)
    assert small.shape == (20, 40, 3)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/a.png",
        "http://10.1.2.3/a.png",
        "http://172.16.0.1/a.png",
        "http://192.168.1.1/a.png",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/a.png",
        "http://evil.example.com/a.png",
        "ftp://img.example.com/a.png",
        "file:///etc/passwd",
    ],
)
async def test_private_or_bad_urls_rejected(dns, url):
    with pytest.raises(InvalidRequestError):
        await load_image(url, 1280)


@respx.mock
async def test_public_url_downloaded(dns):
    respx.get("http://img.example.com/a.png").mock(return_value=httpx.Response(200, content=_png()))
    arr = await load_image("http://img.example.com/a.png", 1280)
    assert arr.shape == (20, 40, 3)


@respx.mock
async def test_redirect_to_private_rejected(dns):
    respx.get("http://img.example.com/r").mock(
        return_value=httpx.Response(302, headers={"location": "http://evil.example.com/x.png"})
    )
    with pytest.raises(InvalidRequestError, match="privat"):
        await load_image("http://img.example.com/r", 1280)


@respx.mock
async def test_size_limit_and_non_image(dns, monkeypatch):
    monkeypatch.setattr(image_input, "MAX_IMAGE_BYTES", 100)
    respx.get("http://img.example.com/big").mock(
        return_value=httpx.Response(200, content=b"x" * 500)
    )
    with pytest.raises(PayloadTooLarge):
        await load_image("http://img.example.com/big", 1280)
    monkeypatch.setattr(image_input, "MAX_IMAGE_BYTES", 10 * 1024 * 1024)
    respx.get("http://img.example.com/txt").mock(return_value=httpx.Response(200, content=b"hai"))
    with pytest.raises(InvalidRequestError, match="bukan gambar"):
        await load_image("http://img.example.com/txt", 1280)
    respx.get("http://img.example.com/404").mock(return_value=httpx.Response(404))
    with pytest.raises(InvalidRequestError, match="404"):
        await load_image("http://img.example.com/404", 1280)
