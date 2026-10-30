"""LangChain & LlamaIndex lewat gateway (endpoint OpenAI-compatible).

pip install langchain-openai llama-index-llms-openai-like
set LGW_API_KEY=lgw_...
python examples/frameworks.py
"""

import os

BASE_URL = os.environ.get("LGW_BASE_URL", "http://127.0.0.1:8000/v1")
KEY = os.environ["LGW_API_KEY"]


def langchain() -> None:
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        base_url=BASE_URL,
        api_key=KEY,
        model="fast",
        max_tokens=40,
        timeout=600,
        default_headers={"X-Caller-Task": "contoh-langchain"},
    )
    print("langchain:", llm.invoke("Sebutkan satu planet di tata surya.").content)
    print("  stream: ", end="")
    for part in llm.stream("Hitung 1 sampai 3."):
        print(part.content, end="", flush=True)
    print()


def llamaindex() -> None:
    from llama_index.llms.openai_like import OpenAILike

    llm = OpenAILike(
        api_base=BASE_URL,
        api_key=KEY,
        model="fast",
        is_chat_model=True,
        max_tokens=40,
        timeout=600,
        context_window=8192,
    )
    print("llamaindex:", llm.complete("Apa warna langit cerah?").text)


if __name__ == "__main__":
    langchain()
    llamaindex()
