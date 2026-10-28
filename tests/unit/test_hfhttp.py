import httpx
import pytest
import respx

from scripts import _hfhttp
from scripts._hfhttp import download_file, file_url

DATA = bytes(range(256)) * 40  # 10.240 byte
URL = file_url("org/repo", "dir/openvino_model.bin")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_hfhttp.time, "sleep", lambda s: None)


def _range_handler(request: httpx.Request) -> httpx.Response:
    rng = request.headers.get("range")
    if not rng:
        return httpx.Response(200, content=DATA)
    start = int(rng.removeprefix("bytes=").rstrip("-"))
    return httpx.Response(206, content=DATA[start:])


@respx.mock
def test_full_download_and_skip_when_complete(tmp_path):
    route = respx.get(URL).mock(side_effect=_range_handler)
    dest = tmp_path / "dir" / "openvino_model.bin"
    assert download_file("org/repo", "dir/openvino_model.bin", dest, len(DATA), quiet=True) == dest
    assert dest.read_bytes() == DATA
    assert not dest.with_name("openvino_model.bin.part").exists()
    download_file("org/repo", "dir/openvino_model.bin", dest, len(DATA), quiet=True)
    assert route.call_count == 1  # sudah lengkap → tidak diunduh ulang


@respx.mock
def test_resume_from_part_file_with_range(tmp_path):
    route = respx.get(URL).mock(side_effect=_range_handler)
    dest = tmp_path / "openvino_model.bin"
    dest.with_name("openvino_model.bin.part").write_bytes(DATA[:4000])
    download_file("org/repo", "dir/openvino_model.bin", dest, len(DATA), quiet=True)
    assert dest.read_bytes() == DATA
    assert route.calls[0].request.headers["range"] == "bytes=4000-"


@respx.mock
def test_retry_after_network_error(tmp_path):
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("stall", request=request)
        return _range_handler(request)

    respx.get(URL).mock(side_effect=flaky)
    dest = tmp_path / "openvino_model.bin"
    download_file("org/repo", "dir/openvino_model.bin", dest, len(DATA), quiet=True)
    assert dest.read_bytes() == DATA and calls["n"] == 2


@respx.mock
def test_server_ignoring_range_restarts_from_zero(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=DATA))
    dest = tmp_path / "openvino_model.bin"
    dest.with_name("openvino_model.bin.part").write_bytes(b"garbage")
    download_file("org/repo", "dir/openvino_model.bin", dest, len(DATA), quiet=True)
    assert dest.read_bytes() == DATA


@respx.mock
def test_size_mismatch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(_hfhttp, "RETRIES", 2)
    respx.get(URL).mock(return_value=httpx.Response(200, content=DATA[:100]))
    with pytest.raises(RuntimeError):
        download_file(
            "org/repo", "dir/openvino_model.bin", tmp_path / "m.bin", len(DATA), quiet=True
        )
