"""LGW-V1-06: X-Request-Tags → requests.tags → GET /admin/usage/by-tag
(biaya per job/tahap/agent)."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Request
from app.services.key_service import key_service
from tests.integration.conftest import drain_finishers

pytestmark = pytest.mark.integration
BODY = {"model": "smart", "messages": [{"role": "user", "content": "x"}]}


async def _chat(c, tags: str) -> dict:
    r = await c.post("/v1/chat/completions", json=BODY, headers={"X-Request-Tags": tags})
    assert r.status_code == 200
    return dict(r.headers)


async def test_cost_per_stage_and_agent_of_one_job(api):
    async with api.client() as c:
        await _chat(c, "job=j1,kind=book,stage=chunk,agent=curator")
        await _chat(c, "job=j1,kind=book,stage=chunk,agent=curator")
        await _chat(c, "job=j1,kind=book,stage=summary,agent=creative")
        await _chat(c, "job=j2,stage=chunk,agent=curator")
        headers = await _chat(c, "job=j3,email=a@b.c,stage=x y,agent=prospector")
    await drain_finishers()
    # tag tidak valid diabaikan + warning, tag valid tetap tersimpan
    assert "request_tag_invalid" in headers["x-gateway-warning"]
    async with SessionLocal() as s:
        tags = (
            await s.execute(select(Request.tags).where(Request.tags.contains({"job": "j3"})))
        ).scalar_one()
    assert tags["agent"] == "prospector" and "email" not in tags and "stage" not in tags
    assert tags["gateway_warnings"] == ["request_tag_invalid"]

    async with SessionLocal() as s:
        admin, _ = await key_service.create_key(s, project_id=None, name="adm", role="admin")
    async with api.client(admin) as c:
        by_stage = (await c.get("/admin/usage/by-tag?key=stage&match=job:j1")).json()
        by_job = (await c.get("/admin/usage/by-tag", params={"key": "job"})).json()
        bad = await c.get("/admin/usage/by-tag?key=stage&match=job")
        bad_key = await c.get("/admin/usage/by-tag?key=Job!")
    stages = {row["stage"]: row for row in by_stage["data"]}
    assert set(stages) == {"chunk", "summary"}
    assert stages["chunk"]["requests"] == 2 and stages["summary"]["requests"] == 1
    total = sum(Decimal(r["cost_usd"]) for r in by_stage["data"])
    assert Decimal(by_stage["total_cost_usd"]) == total
    assert {r["job"]: r["requests"] for r in by_job["data"]} == {"j1": 3, "j2": 1, "j3": 1}
    assert bad.status_code == 400 and bad_key.status_code == 400
