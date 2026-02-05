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


@router.get("/transcript")
async def stream_transcript_sse(
    pipeline=Depends(get_pipeline),
) -> EventSourceResponse:
    queue = pipeline.add_sse_client()
    return EventSourceResponse(
        event_generator(pipeline, queue),
        media_type="text/event-stream",
    )


@router.websocket("/transcript")
async def stream_transcript_ws(
    websocket: WebSocket,
    pipeline=Depends(get_pipeline),
):
    await websocket.accept()
    queue = pipeline.add_ws_client()

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json(
                    {"event": event.event_type.value, "data": event.model_dump()}
                )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "keepalive"})
    except WebSocketDisconnect:
        pass
    finally:
        pipeline.remove_ws_client(queue)
