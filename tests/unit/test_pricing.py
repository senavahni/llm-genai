from dataclasses import dataclass
from decimal import Decimal

from app.services.pricing import model_pricing, price_kind, route_pricing


@dataclass
class M:
    upstream_name: str = "gpt-x"
    device: str = "remote"
    model_type: str = "chat"
    input_cost_per_mtok: Decimal = Decimal(0)
    output_cost_per_mtok: Decimal = Decimal(0)
    cost_per_image: Decimal = Decimal(0)


PAID = M(input_cost_per_mtok=Decimal("0.25"), output_cost_per_mtok=Decimal("2"))
PRICEY = M(input_cost_per_mtok=Decimal("2"), output_cost_per_mtok=Decimal("10"))


def test_zero_price_is_not_labelled_free_unless_free_variant_or_local() -> None:
    assert price_kind(M()) == "unset"
    assert price_kind(M(upstream_name="google/gemma-4-31b-it:free")) == "free"
    assert price_kind(M(device="gpu")) == "local"
    assert price_kind(PAID) == "paid"


def test_model_pricing_only_exposes_numbers_for_paid_models() -> None:
    assert model_pricing(PAID) == {
        "kind": "paid",
        "estimate": True,
        "input_per_mtok": 0.25,
        "output_per_mtok": 2.0,
        "per_image": None,
    }
    free = model_pricing(M(upstream_name="x:free"))
    assert free["kind"] == "free" and free["input_per_mtok"] is None


def test_route_pricing_is_range_over_paid_candidates() -> None:
    p = route_pricing([PAID, M(upstream_name="x:free"), PRICEY])
    assert p["kinds"] == ["free", "paid"]
    assert p["input_per_mtok"] == [0.25, 2.0] and p["output_per_mtok"] == [2.0, 10.0]
    assert route_pricing([M(upstream_name="x:free")])["input_per_mtok"] is None
    assert route_pricing([])["kinds"] == []
