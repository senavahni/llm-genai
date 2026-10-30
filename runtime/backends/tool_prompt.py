"""Render percakapan dengan tools ke pesan teks biasa format Hermes (Qwen2.5), untuk model yang
template chat-nya tidak punya bagian tools (Qwen2-VL lewat `VLMPipeline` + `ChatHistory`).

Hasilnya setara dengan template Qwen2.5: definisi tools di system prompt, tool call assistant
sebagai blok `<tool_call>`, hasil tool sebagai pesan user `<tool_response>`. Keluaran model
di-parse dengan `tool_parsers.parse_tool_output` / `StreamToolParser` yang sama."""

import json
from typing import Any

DEFAULT_SYSTEM = "You are a helpful assistant."

TOOLS_HEADER = (
    "# Tools\n\nYou may call one or more functions to assist with the user query.\n\n"
    "You are provided with function signatures within <tools></tools> XML tags:\n<tools>"
)
TOOLS_FOOTER = (
    "</tools>\n\nFor each function call, return a json object with function name and arguments "
    "within <tool_call></tool_call> XML tags:\n<tool_call>\n"
    '{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>'
)


def tools_system_block(tools: list[dict[str, Any]]) -> str:
    lines = [TOOLS_HEADER]
    for tool in tools:
        lines.append(json.dumps(tool, ensure_ascii=False))
    lines.append(TOOLS_FOOTER)
    return "\n".join(lines)


def _call_block(call: dict[str, Any]) -> str:
    function = call.get("function") or {}
    args = function.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass  # argumen rusak dari klien dikirim apa adanya
    body = json.dumps({"name": function.get("name"), "arguments": args}, ensure_ascii=False)
    return f"<tool_call>\n{body}\n</tool_call>"


def render_hermes_messages(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
) -> list[dict[str, str]]:
    """`messages` = pesan yang kontennya sudah string (role system/user/assistant/tool).
    Kembalikan pesan role system/user/assistant saja dengan konten string."""
    out: list[dict[str, str]] = []
    rest = list(messages)
    system = DEFAULT_SYSTEM
    if rest and rest[0].get("role") == "system":
        system = str(rest.pop(0).get("content") or "")
    if tools:
        system = f"{system}\n\n{tools_system_block(tools)}" if system else tools_system_block(tools)
    out.append({"role": "system", "content": system})

    for msg in rest:
        role = msg.get("role")
        content = str(msg.get("content") or "")
        if role == "assistant" and msg.get("tool_calls"):
            blocks = [_call_block(c) for c in msg["tool_calls"]]
            text = "\n".join(([content] if content else []) + blocks)
            out.append({"role": "assistant", "content": text})
        elif role == "tool":
            response = f"<tool_response>\n{content}\n</tool_response>"
            # hasil tool berturut-turut digabung dalam satu giliran user (seperti template Qwen2.5)
            if out[-1]["role"] == "user" and out[-1]["content"].startswith("<tool_response>"):
                out[-1]["content"] += "\n" + response
            else:
                out.append({"role": "user", "content": response})
        else:
            out.append({"role": str(role), "content": content})
    return out
