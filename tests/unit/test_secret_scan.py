"""Pola secret scan mendeteksi semua jenis key dan hanya menampilkan versi tersamar."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("secret_scan", ROOT / "scripts" / "secret_scan.py")
assert _spec and _spec.loader
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

# dirakit saat runtime agar repo sendiri tidak berisi string berpola secret
FAKES = {
    "openai": "sk-" + "proj-" + "A" * 30,
    "anthropic": "sk-" + "ant-" + "api03-" + "B" * 30,
    "google": "AI" + "za" + "C" * 35,
    "gateway": "lgw_" + "abcd1234" + "_" + "D" * 43,
}


def test_each_pattern_detected_and_masked():
    for kind, secret in FAKES.items():
        found = list(scan.scan_text(f"header Authorization: {secret} end"))
        assert found == [(kind, secret[:6] + "***")], kind


def test_redacted_and_prefix_only_not_flagged():
    clean = "lgw_abcd1234_***REDACTED*** key_prefix=lgw_abcd1234 max_tokens=10 sk-short"
    assert list(scan.scan_text(clean)) == []


def test_scan_logs_reports_location(tmp_path, monkeypatch):
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    (tmp_path / "app.log.2026-10-27").write_text("ok\n" + FAKES["openai"] + "\n", encoding="utf-8")
    (tmp_path / "gambar.png").write_bytes(FAKES["openai"].encode())  # bukan log → dilewati
    assert scan.scan_logs(tmp_path) == ["app.log.2026-10-27:2 openai sk-pro***"]
