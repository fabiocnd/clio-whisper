from typing import Generator
from fastapi import APIRouter, Depends, HTTPException, Request

from clio_api_server.app.models.control import (
    ControlRequest,
    StatusResponse,
    HealthResponse,
)
from clio_api_server.app.models.metrics import Metrics


router = APIRouter(prefix="/v1", tags=["control"])


def get_pipeline(request: Request):
    return request.app.state.pipeline


@router.get("/health", response_model=HealthResponse)
async def health_check(
    pipeline=Depends(get_pipeline),
) -> HealthResponse:
    """
    Health check endpoint.

    Returns the health status of the API and WhisperLive connection.
    """
    status = pipeline.get_status()
    if status.state.value in ("ERROR", "DEGRADED"):
        return HealthResponse.unhealthy(status.last_error or "Unknown error")
    return HealthResponse.healthy(status.ws_connection == "connected")


@router.get("/status", response_model=StatusResponse)
async def get_status(
    pipeline=Depends(get_pipeline),
) -> StatusResponse:
    """
    Get the current pipeline status.

    Returns detailed state including audio device, WebSocket connection,
    queue depths, and any errors.
    """
    return pipeline.get_status()


@router.post("/control/start")
async def start_pipeline(
    pipeline=Depends(get_pipeline),
) -> dict:
    """
    Start the transcription pipeline.

    Initializes audio capture and connects to WhisperLive.
    Only works if pipeline is in STOPPED or ERROR state.
    """
    if pipeline.state.value not in ("STOPPED", "ERROR"):
        raise HTTPException(
            status_code=400, detail=f"Cannot start from state: {pipeline.state.value}"
        )
    success = await pipeline.start()
    if success:
        return {"status": "started", "state": pipeline.state.value}
    raise HTTPException(status_code=500, detail="Failed to start pipeline")


@router.post("/control/stop")
async def stop_pipeline(
    pipeline=Depends(get_pipeline),
) -> dict:
    """
    Stop the transcription pipeline.

    Stops audio capture and disconnects from WhisperLive.
    """
    if pipeline.state.value == "STOPPED":
        return {"status": "already_stopped", "state": pipeline.state.value}
    await pipeline.stop()
    return {"status": "stopped", "state": pipeline.state.value}


@router.get("/metrics", response_model=Metrics)
async def get_metrics(
    pipeline=Depends(get_pipeline),
) -> Metrics:
    """
    Get pipeline metrics.

    Returns counters and gauges for segments, audio frames,
    reconnects, and queue depths.
    """
    return pipeline.get_metrics()
