import json

import pytest

from runtime.backends.tool_parsers import StreamToolParser

CALL = '<tool_call>{"name": "f", "arguments": {"x": 1}}</tool_call>'


def _run(pieces):
    parser = StreamToolParser()
    events = [e for p in pieces for e in parser.feed(p)] + parser.finish()
    content = "".join(v for k, v in events if k == "content")
    calls = [v for k, v in events if k == "tool_call"]
    return content, calls, events


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_markers_split_across_chunks(size):
    text = "Halo " + CALL + " selesai"
    pieces = [text[i : i + size] for i in range(0, len(text), size)]
    content, calls, _ = _run(pieces)
    assert content == "Halo  selesai"
    assert len(calls) == 1 and json.loads(calls[0]["function"]["arguments"]) == {"x": 1}


def test_content_streams_before_block_and_partial_marker_held():
    parser = StreamToolParser()
    assert parser.feed("Teks <to") == [("content", "Teks ")]  # "<to" ditahan
    assert parser.feed("ol bukan") == [("content", "<tool bukan")]


CODER_STYLE = '```xml\n<tools>\n    {"name": "f", "arguments": {"x": 3}}\n</tools>\n```'


def test_lenient_format_parsed_only_for_known_tools():
    from runtime.backends.tool_parsers import parse_lenient, parse_tool_output

    [call] = parse_lenient(CODER_STYLE, {"f"})
    assert json.loads(call["function"]["arguments"]) == {"x": 3}
    assert parse_lenient(CODER_STYLE, {"g"}) == []  # nama bukan tool caller
    assert parse_lenient('Contoh: {"name": "f", "arguments": {}}', {"f"}) == []  # ada teks lain
    assert len(parse_lenient('[{"name": "f", "arguments": {}}, {"name": "f"}]', {"f"})) == 2
    out = parse_tool_output('```json\n{"name": "f", "arguments": {"x": 1}}\n```', ["f"])
    assert out.content is None and len(out.tool_calls) == 1
    assert parse_tool_output("Jawaban biasa", ["f"]).content == "Jawaban biasa"


@pytest.mark.parametrize("size", [1, 4, 1000])
def test_stream_lenient_call_held_then_parsed(size):
    parser = StreamToolParser({"f"})
    pieces = [CODER_STYLE[i : i + size] for i in range(0, len(CODER_STYLE), size)]
    events = [e for p in pieces for e in parser.feed(p)]
    assert events == []  # ditahan: mungkin tool call
    [(kind, call)] = parser.finish()
    assert kind == "tool_call" and call["function"]["name"] == "f"


@pytest.mark.parametrize(
    "text",
    ["```python\ndef f():\n    return 1\n```", "Berikut kodenya:\n```json\n{}\n```", "Halo"],
)
def test_stream_normal_answers_not_held(text):
    parser = StreamToolParser({"f"})
    events = [e for ch in text for e in parser.feed(ch)] + parser.finish()
    assert "".join(v for k, v in events if k == "content") == text
    # konten mengalir sebelum akhir stream (tidak ditahan sampai finish)
    parser = StreamToolParser({"f"})
    streamed = [e for ch in text[:-1] for e in parser.feed(ch)]
    assert streamed, text


def test_two_calls_and_broken_or_unclosed_blocks():
    content, calls, _ = _run([CALL, CALL.replace('"x": 1', '"x": 2')])
    assert [json.loads(c["function"]["arguments"])["x"] for c in calls] == [1, 2]
    content, calls, _ = _run(["<tool_call>{rusak</tool_call>"])
    assert calls == [] and content == "<tool_call>{rusak</tool_call>"
    content, calls, _ = _run(['<tool_call>{"name": "f"'])  # stream terputus
    assert calls == [] and content == '<tool_call>{"name": "f"'
