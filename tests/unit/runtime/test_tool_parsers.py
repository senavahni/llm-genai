import json

from runtime.backends.tool_parsers import parse_hermes

CALL = '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Bandung"}}\n</tool_call>'


def test_single_call():
    out = parse_hermes(CALL)
    assert out.content is None
    (call,) = out.tool_calls
    assert call["type"] == "function" and call["id"].startswith("call_")
    assert call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "Bandung"}


def test_multiple_calls_and_surrounding_text():
    text = "Saya cek dulu.\n" + CALL + "\n" + CALL.replace("Bandung", "Jakarta")
    out = parse_hermes(text)
    assert out.content == "Saya cek dulu."
    cities = [json.loads(c["function"]["arguments"])["city"] for c in out.tool_calls]
    assert cities == ["Bandung", "Jakarta"]
    assert len({c["id"] for c in out.tool_calls}) == 2


def test_plain_text_and_broken_json_kept_as_content():
    assert parse_hermes("Cuaca Bandung cerah.").tool_calls == []
    broken = "<tool_call>{rusak</tool_call>"
    out = parse_hermes(broken)
    assert out.tool_calls == [] and out.content == broken


def test_parameters_key_and_string_arguments():
    out = parse_hermes('<tool_call>{"name": "f", "parameters": {"x": 1}}</tool_call>')
    assert json.loads(out.tool_calls[0]["function"]["arguments"]) == {"x": 1}
    out = parse_hermes('<tool_call>{"name": "f", "arguments": "{\\"x\\": 2}"}</tool_call>')
    assert out.tool_calls[0]["function"]["arguments"] == '{"x": 2}'
