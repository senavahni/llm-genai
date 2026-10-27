"""Fixture kontrak tool-calling: user → assistant tool_calls ×2 (paralel) → tool ×2 → final."""

from app.schemas.unified import UnifiedChatRequest

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Cuaca kota",
            "parameters": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "parameters": {"type": "object", "properties": {"tz": {"type": "string"}}},
        },
    },
]


def multi_turn_request(call_ids: tuple[str, str] = ("call_a", "call_b")) -> UnifiedChatRequest:
    return UnifiedChatRequest.model_validate(
        {
            "messages": [
                {"role": "system", "content": "Kamu asisten."},
                {"role": "system", "content": "Jawab singkat."},
                {"role": "user", "content": "Cuaca & jam di Bandung?"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_ids[0],
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"city":"Bandung"}'},
                        },
                        {
                            "id": call_ids[1],
                            "type": "function",
                            "function": {"name": "get_time", "arguments": '{"tz":"Asia/Jakarta"}'},
                        },
                    ],
                },
                {"role": "tool", "tool_call_id": call_ids[0], "content": '{"temp":24}'},
                {"role": "tool", "tool_call_id": call_ids[1], "content": "10:00"},
            ],
            "tools": TOOLS,
            "tool_choice": "auto",
        }
    )
