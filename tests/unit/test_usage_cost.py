import uuid
from decimal import Decimal

from app.schemas.catalog import ModelConfig
from app.schemas.unified import Usage
from app.services.context import Outcome
from app.services.usage_service import cost_usd, strip_images


def _model(**kw) -> ModelConfig:
    return ModelConfig(
        id=uuid.uuid4(),
        alias="m",
        provider_code="openai",
        upstream_name="m",
        model_type="chat",
        **kw,
    )


def test_cost_decimal_exact():  # AC3: tanpa error float
    m = _model(input_cost_per_mtok=Decimal("0.15"), output_cost_per_mtok=Decimal("0.6"))
    out = Outcome(usage=Usage(prompt_tokens=1, completion_tokens=3))
    assert cost_usd(m, out) == Decimal("0.00000195")
    assert isinstance(cost_usd(m, out), Decimal)
    many = Outcome(usage=Usage(prompt_tokens=10_000_000, completion_tokens=1))
    assert cost_usd(m, many) == Decimal("1.50000060")


def test_cost_cached_tokens_and_images():
    m = _model(
        input_cost_per_mtok=Decimal("3"),
        output_cost_per_mtok=Decimal("15"),
        cost_per_image=Decimal("0.002"),
        config={"cached_input_cost_per_mtok": "0.3"},
    )
    out = Outcome(usage=Usage(prompt_tokens=1000, completion_tokens=0, cached_tokens=400))
    # 600×3 + 400×0.3 = 1920 / 1e6
    assert cost_usd(m, out) == Decimal("0.00192000")
    no_cache_price = _model(input_cost_per_mtok=Decimal("3"))
    assert cost_usd(no_cache_price, out) == Decimal("0.00300000")
    images = _model(cost_per_image=Decimal("0.002"))
    assert cost_usd(images, Outcome(image_count=3)) == Decimal("0.00600000")
    assert cost_usd(None, out) == Decimal(0)


def test_strip_images_only_large_base64():
    small = "data:image/png;base64,AAAA"
    big = "data:image/png;base64," + "A" * 200_000
    text = "kata " * 50_000  # teks panjang biasa tidak dibuang
    out = strip_images({"a": [small, big], "b": {"c": big}, "t": text, "raw": b"xx"})
    assert out["a"][0] == small and out["a"][1].startswith("<image omitted:")
    assert out["b"]["c"].startswith("<image omitted:") and out["t"] == text
    assert out["raw"] == "<image omitted: 2 bytes>"
