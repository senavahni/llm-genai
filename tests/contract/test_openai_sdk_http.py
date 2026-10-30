"""Contract test: SDK `openai` resmi (klien HTTP bawaannya) → gateway di uvicorn sungguhan.
Memastikan respons, SSE, header & error bisa diparse SDK persis seperti terhadap API OpenAI."""

import base64

import openai
import pytest

from tests.fakes.server import serve

pytestmark = [pytest.mark.integration, pytest.mark.contract]


def _client(base: str, key: str) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(api_key=key, base_url=f"{base}/v1", max_retries=0, timeout=30)


async def test_chat_stream_completions_models_images(api):
    async with serve(api.app) as base:
        client = _client(base, api.key)

        raw = await client.chat.completions.with_raw_response.create(
            model="smart", messages=[{"role": "user", "content": "hai"}]
        )
        chat = raw.parse()
        assert chat.choices[0].message.content == "Hello!"
        assert chat.usage and chat.usage.total_tokens == 6
        assert raw.headers["x-gateway-model"] and raw.headers["x-request-id"]

        stream = await client.chat.completions.create(
            model="smart",
            messages=[{"role": "user", "content": "hai"}],
            stream=True,
            stream_options={"include_usage": True},
        )
        text, usage = "", None
        async for chunk in stream:
            if chunk.choices:
                text += chunk.choices[0].delta.content or ""
            if chunk.usage:
                usage = chunk.usage
        assert text == "Hello!" and usage and usage.completion_tokens == 3

        fim = await client.completions.create(
            model="autocomplete", prompt="def f(n):\n", suffix="\n", max_tokens=16
        )
        assert fim.choices[0].text == "    return n > 1"

        ids = {m.id async for m in client.models.list()}
        assert {"smart", "autocomplete", "image"} <= ids

        img = await client.images.generate(
            model="image", prompt="kucing", size="512x512", response_format="b64_json"
        )
        assert base64.b64decode(img.data[0].b64_json or "").startswith(b"\x89PNG")


async def test_errors_map_to_sdk_exceptions(api):
    async with serve(api.app) as base:
        with pytest.raises(openai.AuthenticationError):
            await _client(base, "lgw_salah").models.list()
        client = _client(base, api.other_key)  # agent-b hanya local/* & image
        with pytest.raises(openai.PermissionDeniedError) as exc:
            await client.chat.completions.create(
                model="smart", messages=[{"role": "user", "content": "x"}]
            )
        assert exc.value.code == "model_not_allowed"
        with pytest.raises(openai.BadRequestError):
            await _client(base, api.key).chat.completions.create(model="smart", messages=[])
