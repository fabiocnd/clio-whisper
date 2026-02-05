import asyncio
import json
from typing import AsyncGenerator, Generator

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/v1/stream", tags=["streaming"])


def get_pipeline(request: Request):
    return request.app.state.pipeline


async def event_generator(
    pipeline,
    queue: asyncio.Queue,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events from the pipeline event queue.

    Yields JSON-formatted events for each transcript update.
    """
    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
            event_data = event.model_dump_json()
            yield f"data: {event_data}\n\n"
    except asyncio.TimeoutError:
        yield ""
    except asyncio.CancelledError:
        raise
    except Exception:
        yield ""
    finally:
        pipeline.remove_sse_client(queue)


async def event_generator_redis(
    pipeline,
    queue: asyncio.Queue,
) -> AsyncGenerator[str, None]:
    """
    Generate SSE events from the Redis pipeline.

    Yields JSON-formatted events for each transcript update.
    """
    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
            yield f"data: {json.dumps(event)}\n\n"
    except asyncio.TimeoutError:
        yield ""
    except asyncio.CancelledError:
        raise
    except Exception:
        yield ""
    finally:
        pipeline.remove_sse_client(queue)


@router.get("/transcript")
async def stream_transcript_sse(
    pipeline=Depends(get_pipeline),
) -> EventSourceResponse:
    """
    Stream transcript events via Server-Sent Events (SSE).

    Returns a continuous stream of transcription events including
    partial results, final segments, and system events.
    Connect to this endpoint to receive real-time updates.
    """
    queue = pipeline.add_sse_client()

    if hasattr(pipeline, "stream_manager"):
        return EventSourceResponse(
            event_generator_redis(pipeline, queue),
            media_type="text/event-stream",
        )

    return EventSourceResponse(
        event_generator(pipeline, queue),
        media_type="text/event-stream",
    )


@router.websocket("/transcript")
async def stream_transcript_ws(
    websocket: WebSocket,
    pipeline=Depends(get_pipeline),
):
    """
    Stream transcript events via WebSocket.

    Provides the same real-time transcription events as SSE
    but over a bidirectional WebSocket connection.
    """
    await websocket.accept()
    queue = pipeline.add_ws_client()

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                if hasattr(pipeline, "stream_manager"):
                    await websocket.send_json(event)
                else:
                    await websocket.send_json(
                        {"event": event.event_type.value, "data": event.model_dump()}
                    )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive"})
    except WebSocketDisconnect:
        pass
    finally:
        pipeline.remove_ws_client(queue)
