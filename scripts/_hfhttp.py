"""Downloader HTTPS sederhana untuk file Hugging Face: resume (Range), retry, cek ukuran.

Dibuat karena jalur unduh huggingface_hub (termasuk Xet) macet di 0 byte pada jaringan ini,
sementara HTTPS biasa ke CDN HF berjalan normal. Metadata (daftar file & ukuran) tetap memakai
HfApi."""

import fnmatch
import os
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
CHUNK = 1024 * 1024
RETRIES = 20


def file_url(repo: str, filename: str, revision: str = "main") -> str:
    return f"{HF_ENDPOINT}/{repo}/resolve/{revision}/{filename}"


def _headers() -> dict[str, str]:
    token = os.environ.get("HF_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


def download_file(
    repo: str, filename: str, dest: Path, expected_size: int | None = None, *, quiet: bool = False
) -> Path:
    """Unduh ke `dest` (resume dari `dest.part`). Lewati bila ukuran sudah cocok."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        return dest
    part = dest.with_name(dest.name + ".part")
    url = file_url(repo, filename)
    last_print = 0.0
    for attempt in range(1, RETRIES + 1):
        have = part.stat().st_size if part.exists() else 0
        if expected_size is not None and have >= expected_size:
            break
        headers = {**_headers(), **({"Range": f"bytes={have}-"} if have else {})}
        try:
            with httpx.stream(
                "GET",
                url,
                headers=headers,
                follow_redirects=True,
                timeout=httpx.Timeout(60.0, connect=20.0),
            ) as r:
                if r.status_code == 416:  # sudah lengkap
                    break
                r.raise_for_status()
                mode = "ab" if have and r.status_code == 206 else "wb"
                if mode == "wb":
                    have = 0
                total = expected_size or (have + int(r.headers.get("content-length", 0)))
                start, start_have = time.monotonic(), have
                with part.open(mode) as fh:
                    for block in r.iter_bytes(CHUNK):
                        fh.write(block)
                        have += len(block)
                        now = time.monotonic()
                        if not quiet and now - last_print > 15:
                            rate = (have - start_have) / max(now - start, 1e-6) / 1e6
                            pct = f"{have / total:.0%}" if total else "?"
                            print(
                                f"  {filename}: {have / 1e6:,.0f} MB ({pct}) {rate:.1f} MB/s",
                                flush=True,
                            )
                            last_print = now
            if expected_size is None or have >= expected_size:
                break
        except (httpx.HTTPError, OSError) as exc:
            wait = min(60, 2 * attempt)
            if not quiet:
                print(
                    f"  {filename}: {type(exc).__name__} ({exc}); coba lagi {wait}s "
                    f"[{attempt}/{RETRIES}]",
                    flush=True,
                )
            time.sleep(wait)
    else:
        raise RuntimeError(f"gagal mengunduh {repo}/{filename} setelah {RETRIES} percobaan")
    size = part.stat().st_size
    if expected_size is not None and size != expected_size:
        raise RuntimeError(f"{filename}: ukuran {size} != {expected_size}")
    part.replace(dest)
    return dest


def repo_files(repo: str) -> dict[str, int]:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, files_metadata=True)
    return {s.rfilename: s.size or 0 for s in info.siblings or []}


def download_repo(
    repo: str, dest_dir: Path, allow: Iterable[str], ignore: Iterable[str] = ()
) -> Path:
    """Snapshot sebagian repo (pola allow/ignore) ke `dest_dir`, struktur folder dipertahankan."""
    allow, ignore = list(allow), list(ignore)
    files = {
        f: s
        for f, s in repo_files(repo).items()
        if any(fnmatch.fnmatch(f, p) for p in allow)
        and not any(fnmatch.fnmatch(f, p) for p in ignore)
    }
    print(f"{repo}: {len(files)} file, {sum(files.values()) / 1e9:.2f} GB → {dest_dir}")
    for name, size in sorted(files.items(), key=lambda kv: kv[1]):
        download_file(repo, name, dest_dir / name, size or None)
    return dest_dir
