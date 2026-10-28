"""Checksum artefak model. Model OpenVINO berupa folder IR, jadi digest folder dihitung dari
sha256 tiap file (path relatif terurut), sehingga perubahan isi/nama file apa pun terdeteksi."""

import hashlib
from pathlib import Path

_CHUNK = 8 * 1024 * 1024
# file sampingan yang boleh berubah tanpa mengubah model
_IGNORED = {".gitattributes", "README.md"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(_CHUNK):
            h.update(block)
    return h.hexdigest()


def sha256_artifact(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file() and p.name not in _IGNORED):
        rel = f.relative_to(path).as_posix()
        h.update(f"{rel}\0{sha256_file(f)}\n".encode())
    return h.hexdigest()
