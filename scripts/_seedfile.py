"""Helper bersama script model: baca seed_models.yaml dan patch nilai per model TANPA merusak
komentar/format file (PyYAML dump akan membuang komentar)."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED_FILE = ROOT / "scripts" / "seed_models.yaml"


def load_seed(path: Path = SEED_FILE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def local_models(data: dict[str, Any], only: set[str] | None = None) -> list[dict[str, Any]]:
    models = [m for m in data["models"] if m.get("device", "remote") != "remote"]
    if only:
        models = [m for m in models if m["alias"] in only or m["alias"].split("/")[-1] in only]
    return models


def patch_model_value(alias: str, key: str, value: Any, path: Path = SEED_FILE) -> bool:
    """Ganti/tambah baris `key: value` di blok model `alias` (format blok multi-baris)."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(
        (i for i, ln in enumerate(lines) if re.match(rf"\s*- alias:\s*{re.escape(alias)}\s*$", ln)),
        None,
    )
    if start is None:
        return False
    indent = re.match(r"(\s*)-", lines[start]).group(1) + "  "  # type: ignore[union-attr]
    # blok berakhir di baris non-kosong pertama yang tidak menjorok lebih dalam dari item
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip() and not lines[i].startswith(indent)
        ),
        len(lines),
    )
    rendered = f"{indent}{key}: {value}\n"
    for i in range(start + 1, end):
        if re.match(rf"{re.escape(indent)}{re.escape(key)}:", lines[i]):
            lines[i] = rendered
            break
    else:
        anchor = next(
            (i for i in range(start + 1, end) if lines[i].startswith(indent + "vram_mb:")), start
        )
        lines.insert(anchor + 1, rendered)
    path.write_text("".join(lines), encoding="utf-8")
    return True
