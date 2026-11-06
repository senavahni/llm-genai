"""Info harga ESTIMASI untuk pemilih model di konsol & klien (`x_pricing` di /v1/models).

Harga di katalog diisi manual dari halaman pricing provider, jadi selalu estimasi. Harga 0
dibedakan: model lokal (gratis, jalan di mesin sendiri), varian gratis provider (nama upstream
berakhiran `:free`, mis. OpenRouter), dan "belum diisi" (harga 0 yang BUKAN gratis — jangan
dilabeli gratis agar operator tidak salah pilih).
"""

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, Literal, Protocol

PriceKind = Literal["local", "free", "paid", "unset"]
FREE_SUFFIX = ":free"


class _Priced(Protocol):
    """Baris ORM `Model` maupun snapshot `ModelConfig` (frozen) — cukup bisa dibaca."""

    @property
    def device(self) -> str: ...
    @property
    def upstream_name(self) -> str: ...
    @property
    def model_type(self) -> str: ...
    @property
    def input_cost_per_mtok(self) -> Decimal: ...
    @property
    def output_cost_per_mtok(self) -> Decimal: ...
    @property
    def cost_per_image(self) -> Decimal: ...


def _num(value: Decimal | None) -> float:
    return float(value or 0)


def price_kind(model: _Priced) -> PriceKind:
    if model.device != "remote":
        return "local"
    if model.upstream_name.endswith(FREE_SUFFIX):
        return "free"
    costs = (model.input_cost_per_mtok, model.output_cost_per_mtok, model.cost_per_image)
    return "paid" if any(_num(c) > 0 for c in costs) else "unset"


def model_pricing(model: _Priced) -> dict[str, Any]:
    kind = price_kind(model)
    paid = kind == "paid"
    return {
        "kind": kind,
        "estimate": True,
        "input_per_mtok": _num(model.input_cost_per_mtok) if paid else None,
        "output_per_mtok": _num(model.output_cost_per_mtok) if paid else None,
        "per_image": _num(model.cost_per_image) if paid and model.model_type == "image" else None,
    }


def route_pricing(models: Iterable[_Priced]) -> dict[str, Any]:
    """Rentang harga kandidat route (route bisa jatuh ke kandidat mana pun saat fallback)."""
    items = [model_pricing(m) for m in models]
    paid = [p for p in items if p["kind"] == "paid"]
    inputs = [p["input_per_mtok"] for p in paid]
    outputs = [p["output_per_mtok"] for p in paid]
    return {
        "kinds": sorted({p["kind"] for p in items}),
        "estimate": True,
        "input_per_mtok": [min(inputs), max(inputs)] if inputs else None,
        "output_per_mtok": [min(outputs), max(outputs)] if outputs else None,
    }
