from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Metrics(BaseModel):
    segments_received: int = 0
    segments_committed: int = 0
    segments_dropped: int = 0
    audio_frames_sent: int = 0
    audio_frames_dropped: int = 0
    reconnect_count: int = 0
    connected_sse_clients: int = 0
    connected_ws_clients: int = 0
    audio_queue_depth: int = 0
    audio_queue_overflow: bool = False
    event_queue_depth: int = 0
    last_segment_timestamp: Optional[datetime] = None
    questions_extracted: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "segments_received": self.segments_received,
            "segments_committed": self.segments_committed,
            "segments_dropped": self.segments_dropped,
            "audio_frames_sent": self.audio_frames_sent,
            "audio_frames_dropped": self.audio_frames_dropped,
            "reconnect_count": self.reconnect_count,
            "connected_sse_clients": self.connected_sse_clients,
            "connected_ws_clients": self.connected_ws_clients,
            "audio_queue_depth": self.audio_queue_depth,
            "audio_queue_overflow": int(self.audio_queue_overflow),
            "event_queue_depth": self.event_queue_depth,
            "questions_extracted": self.questions_extracted,
        }
