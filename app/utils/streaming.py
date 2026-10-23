import json
from typing import AsyncGenerator, Generator, Any
from fastapi.responses import StreamingResponse
import asyncio


async def create_sse_stream(
    data_generator: AsyncGenerator[Any, None],
    event_type: str = "message"
) -> StreamingResponse:
    """
    Create Server-Sent Events (SSE) streaming response
    
    Usage:
        async def generate_data():
            for i in range(10):
                yield {"content": f"chunk {i}"}
        
        return await create_sse_stream(generate_data())
    """
    
    async def event_stream():
        try:
            async for data in data_generator:
                # Format as SSE
                if isinstance(data, dict):
                    yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                else:
                    yield f"event: {event_type}\ndata: {json.dumps({'content': str(data)})}\n\n"
            
            # Send completion event
            yield f"event: done\ndata: {json.dumps({'status': 'completed'})}\n\n"
            
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


async def stream_text(
    text_generator: AsyncGenerator[str, None],
    model: str,
    created: int
) -> StreamingResponse:
    """
    Stream text generation in OpenAI-compatible format
    
    Usage:
        async def generate_text():
            for word in ["Hello", " world", "!"]:
                yield word
        
        return await stream_text(generate_text(), "gpt-4", 1234567890)
    """
    
    async def openai_stream():
        chunk_id = f"chatcmpl-{created}"
        
        try:
            async for text_chunk in text_generator:
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": text_chunk
                            },
                            "finish_reason": None
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                await asyncio.sleep(0)  # Yield control to event loop
            
            # Send final chunk with finish_reason
            final_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }
                ]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            error_chunk = {
                "error": {
                    "message": str(e),
                    "type": "server_error"
                }
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
    
    return StreamingResponse(
        openai_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


def sync_stream_text(
    text_generator: Generator[str, None, None],
    model: str,
    created: int
) -> StreamingResponse:
    """
    Synchronous version of stream_text
    """
    
    def openai_stream():
        chunk_id = f"chatcmpl-{created}"
        
        try:
            for text_chunk in text_generator:
                chunk = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": text_chunk
                            },
                            "finish_reason": None
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
            
            final_chunk = {
                "id": chunk_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }
                ]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            error_chunk = {
                "error": {
                    "message": str(e),
                    "type": "server_error"
                }
            }
            yield f"data: {json.dumps(error_chunk)}\n\n"
    
    return StreamingResponse(
        openai_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )