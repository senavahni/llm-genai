"""LGW-V1-04 lewat endpoint Gateway: MCP cukup kirim input + input_type/X-Priority; prefix &
priority diatur Gateway; klien lama embed-default tidak berubah."""

import pytest

from tests.integration.conftest import _project_key, drain_finishers

pytestmark = pytest.mark.integration
QUERY_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "  # noqa: E501
)


async def test_query_prefix_priority_and_legacy_client(api):
    key = await _project_key("mcp-e", ["embed-local", "embed-default", "local/*", "openai/*"])
    local, remote = api.providers["openvino"], api.providers["openai"]
    async with api.client(key) as c:
        r = await c.post(
            "/v1/embeddings",
            json={"model": "embed-local", "input": ["siapa pesaing kami?"], "input_type": "query"},
            headers={"X-Priority": "bulk"},
        )
        assert r.status_code == 200, r.text
        sent = local.requests[-1]
        assert sent["inputs"] == [QUERY_PREFIX + "siapa pesaing kami?"]
        assert sent["priority"] == "bulk" and "input_type" not in sent

        r = await c.post(
            "/v1/embeddings",
            json={
                "model": "embed-local",
                "input": ["dokumen"],
                "provider_options": {"truncate": True},
            },
        )
        assert r.status_code == 200
        sent = local.requests[-1]
        assert sent["inputs"] == ["dokumen"]  # document: tanpa prefix
        assert sent["priority"] == "interactive" and sent["truncate"] is True

        # klien lama: embed-default persis seperti sebelum v1 (tanpa opsi gateway)
        r = await c.post("/v1/embeddings", json={"model": "embed-default", "input": "x"})
        assert r.status_code == 200
        assert remote.requests[-1] == {"inputs": ["x"], "dimensions": None}

        bad = await c.post(
            "/v1/embeddings",
            json={"model": "embed-local", "input": "x"},
            headers={"X-Priority": "now"},
        )
        bad_type = await c.post(
            "/v1/embeddings", json={"model": "embed-local", "input": "x", "input_type": "passage"}
        )
    await drain_finishers()
    assert bad.status_code == 400 and bad_type.status_code == 400
