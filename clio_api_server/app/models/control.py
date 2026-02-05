from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PipelineState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class ControlRequest(BaseModel):
    action: str


class StatusResponse(BaseModel):
    state: PipelineState
    audio_device: Optional[str] = None
    sample_rate: int = 0
    ws_connection: str = "disconnected"
    queue_depths: dict = Field(default_factory=dict)
    last_error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def stopped(cls) -> "StatusResponse":
        return cls(state=PipelineState.STOPPED)

    @classmethod
    def running(cls, audio_device: str, sample_rate: int, ws_status: str) -> "StatusResponse":
        return cls(
            state=PipelineState.RUNNING,
            audio_device=audio_device,
            sample_rate=sample_rate,
            ws_connection=ws_status,
        )


class HealthResponse(BaseModel):
    status: str
    whisperlive_ready: bool
    whisperlive_connected: bool
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: dict = Field(default_factory=dict)

    @classmethod
    def healthy(cls, connected: bool = True) -> "HealthResponse":
        return cls(
            status="healthy" if connected else "degraded",
            whisperlive_ready=True,
            whisperlive_connected=connected,
        )

    @classmethod
    def unhealthy(cls, reason: str) -> "HealthResponse":
        return cls(
            status="unhealthy",
            whisperlive_ready=False,
            whisperlive_connected=False,
            details={"reason": reason},
        )
