import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from clio_api_server.app.models.events import StreamingEvent
from clio_api_server.app.services.pipeline import Pipeline, get_pipeline


router = APIRouter(prefix="/v1/stream", tags=["streaming"])


async def event_generator(
    pipeline: Pipeline,
    queue: asyncio.Queue,
) -> AsyncGenerator[str, None]:
    try:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=30.0)
            event_data = event.model_dump_json()
            yield f"event: {event.event_type.value}\ndata: {event_data}\n\n"
    except asyncio.TimeoutError:
        yield ""
    except asyncio.CancelledError:
        raise
    except Exception:
        yield ""


@router.get("/transcript")
async def stream_transcript_sse(
    pipeline: Pipeline = Depends(get_pipeline),
) -> EventSourceResponse:
    queue = pipeline.add_sse_client()
    return EventSourceResponse(
        event_generator(pipeline, queue),
        media_type="text/event-stream",
    )


@router.websocket("/transcript")
async def stream_transcript_ws(
    request: Request,
    pipeline: Pipeline = Depends(get_pipeline),
):
    queue = pipeline.add_ws_client()
    pipeline._ws_clients.append(queue)

    try:
        while not request.is_disconnected():
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                await request.send(
                    f"event: {event.event_type.value}\ndata: {json.dumps(event.model_dump())}\n\n"
                )
            except asyncio.TimeoutError:
                await request.send(": keepalive\n\n")
    except Exception:
        pass
    finally:
        if queue in pipeline._ws_clients:
            pipeline._ws_clients.remove(queue)
