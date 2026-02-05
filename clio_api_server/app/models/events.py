from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    STATUS = "status"
    SYSTEM = "system"
    ERROR = "error"
    LANGUAGE_DETECTED = "language_detected"
    SERVER_READY = "server_ready"
    WAIT = "wait"
    DISCONNECT = "disconnect"


class ServerStatus(str, Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    BUSY = "busy"
    WAITING = "waiting"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class WhisperLiveSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str = ""
    completed: bool = False


class WhisperLiveEvent(BaseModel):
    uid: Optional[str] = None
    message: Optional[str] = None
    status: Optional[str] = None
    language: Optional[str] = None
    language_prob: Optional[float] = None
    segments: Optional[List[WhisperLiveSegment]] = None
    translated_segments: Optional[List[WhisperLiveSegment]] = None
    backend: Optional[str] = None


class StreamingEvent(BaseModel):
    event_id: str
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = Field(default_factory=dict)
    segment_id: Optional[int] = None
    text: Optional[str] = None
    client_uid: Optional[str] = None

    @classmethod
    def from_whisper_event(cls, event: WhisperLiveEvent) -> List["StreamingEvent"]:
        events = []
        if event.message == "SERVER_READY":
            events.append(cls(
                event_id=f"sr_{datetime.utcnow().timestamp()}",
                event_type=EventType.SERVER_READY,
                data={"backend": event.backend, "uid": event.uid},
            ))
        elif event.message == "DISCONNECT":
            events.append(cls(
                event_id=f"dc_{datetime.utcnow().timestamp()}",
                event_type=EventType.DISCONNECT,
                data={"uid": event.uid},
            ))
        elif event.status == "WAIT":
            events.append(cls(
                event_id=f"wait_{datetime.utcnow().timestamp()}",
                event_type=EventType.WAIT,
                data={"message": event.message},
            ))
        elif event.language:
            events.append(cls(
                event_id=f"lang_{datetime.utcnow().timestamp()}",
                event_type=EventType.LANGUAGE_DETECTED,
                data={"language": event.language, "probability": event.language_prob},
            ))
        if event.segments:
            for seg in event.segments:
                event_type = EventType.FINAL if seg.completed else EventType.PARTIAL
                events.append(cls(
                    event_id=f"seg_{seg.id}_{datetime.utcnow().timestamp()}",
                    event_type=event_type,
                    data={"id": seg.id, "start": seg.start, "end": seg.end, "completed": seg.completed},
                    segment_id=seg.id,
                    text=seg.text.strip() if seg.text else None,
                    client_uid=event.uid,
                ))
        if event.status == "ERROR":
            events.append(cls(
                event_id=f"err_{datetime.utcnow().timestamp()}",
                event_type=EventType.ERROR,
                data={"message": event.message},
            ))
        return events
