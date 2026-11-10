"""LGW-V1-04 sisi Gateway: input_type → prefix instruksi, truncate/priority hanya ke runtime
lokal, klien lama (embed-default) tidak terpengaruh."""

import uuid

import pytest

from app.schemas.catalog import ModelConfig
from app.services.embedding_service import (
    apply_instruction,
    input_type_of,
    options_for,
    parse_priority,
)
from app.utils.errors import InvalidRequestError

PREFIX = "Instruct: cari\nQuery: "


def _model(device: str, **config) -> ModelConfig:
    return ModelConfig(
        id=uuid.uuid4(),
        alias="local/e" if device != "remote" else "openai/e",
        provider_code="openvino" if device != "remote" else "openai",
        upstream_name="e",
        model_type="embedding",
        device=device,
        config=config,
    )


LOCAL = _model("gpu", embedding_instructions={"query": PREFIX, "document": ""})
REMOTE = _model("remote")


def test_prefix_only_for_query_on_models_with_instructions():
    assert apply_instruction(LOCAL, ["a", "b"], "query") == [PREFIX + "a", PREFIX + "b"]
    assert apply_instruction(LOCAL, ["a"], "document") == ["a"]
    assert apply_instruction(REMOTE, ["a"], "query") == ["a"]  # model tanpa instruksi
    assert apply_instruction(LOCAL, [[1, 2]], "query") == [[1, 2]]  # token-ID tidak diubah


@pytest.mark.parametrize(
    ("opts", "expected"), [({}, "document"), ({"input_type": "query"}, "query")]
)
def test_input_type_default_document(opts, expected):
    assert input_type_of(opts) == expected


def test_invalid_input_type_and_priority():
    with pytest.raises(InvalidRequestError, match="input_type"):
        input_type_of({"input_type": "passage"})
    with pytest.raises(InvalidRequestError, match="X-Priority"):
        parse_priority("urgent")
    assert parse_priority(None) == "interactive" and parse_priority(" Bulk ") == "bulk"


def test_gateway_options_not_leaked_to_remote_provider():
    opts = {"input_type": "query", "truncate": True, "user": "u1"}
    assert options_for(REMOTE, opts, "bulk") == {"user": "u1"}  # embed-default tetap bersih
    assert options_for(LOCAL, opts, "bulk") == {"user": "u1", "priority": "bulk", "truncate": True}
    assert options_for(LOCAL, {}, "interactive") == {"priority": "interactive"}
