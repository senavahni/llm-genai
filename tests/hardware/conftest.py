"""Test hardware: model OpenVINO nyata dari katalog (`scripts/seed_models.yaml`), dijalankan
hanya dengan `pytest --hardware`. Model harus sudah diunduh/dikonversi (TASK-09)."""

from typing import Any

import pytest

from runtime.core.catalog import LocalModelSpec
from scripts._seedfile import load_seed, local_models


def catalog_spec(alias: str, **config: Any) -> LocalModelSpec:
    item = next(m for m in local_models(load_seed()) if m["alias"] == alias)
    return LocalModelSpec(
        alias=item["alias"],
        upstream_name=item["upstream_name"],
        device=item["device"],
        runtime_backend=item["runtime_backend"],
        model_type=item["model_type"],
        artifact_path=item["artifact_path"],
        artifact_sha256=item.get("artifact_sha256"),
        vram_mb=int(item["vram_mb"]),
        is_pinned=bool(item.get("is_pinned")),
        supports_fim=bool(item.get("supports_fim")),
        config={**(item.get("config") or {}), **config},
    )


@pytest.fixture
def spec_for():
    return catalog_spec
