"""
Redis Consumer Workers for Clio Whisper.

Provides worker implementations for processing messages from Redis Streams.
These workers run in parallel and handle:
- Transcription: Audio chunks → Transcription segments
- Aggregation: Segments → Consolidated transcript
- Broadcasting: Events → SSE/WebSocket clients
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Any

from loguru import logger

from clio_api_server.app.core.config import get_settings
from clio_api_server.app.models.transcript import (
    ConsolidatedTranscript,
    Question,
    SegmentStatus,
    TranscriptSegment,
    UnconsolidatedTranscript,
)
from clio_api_server.app.services.redis_stream_manager import (
    RedisStreamManager,
    StreamType,
)


class BaseWorker(ABC):
    """Base class for Redis stream workers."""

    def __init__(self, stream_manager: RedisStreamManager):
        self.stream_manager = stream_manager
        self.settings = get_settings()
        self._running = False

    @abstractmethod
    async def process_message(self, msg_id: str, data: dict[str, Any]) -> None:
        """Process a single message from the stream."""
        pass

    async def start(self) -> None:
        """Start the worker."""
        self._running = True
        logger.info(f"{self.__class__.__name__} started")

    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        logger.info(f"{self.__class__.__name__} stopped")


class TranscriptionWorker(BaseWorker):
    """
    Worker that processes audio chunks and sends to WhisperLive.

    This worker:
    1. Reads audio chunks from Redis stream
    2. Sends to WhisperLive WebSocket
    3. Publishes segments to the segments stream
    """

    def __init__(self, stream_manager: RedisStreamManager):
        super().__init__(stream_manager)
        self._audio_buffer: dict[str, bytes] = {}

    async def process_message(self, msg_id: str, data: dict[str, Any]) -> None:
        """Process audio chunk and send to WhisperLive."""
        correlation_id = data.get("correlation_id")
        timestamp = float(data.get("timestamp", time.time()))

        audio_hex = data.get("audio")
        if not audio_hex:
            logger.warning(f"No audio data in message {msg_id}")
            return

        audio_chunk = bytes.fromhex(audio_hex)
        logger.debug(f"Processing audio chunk {msg_id}: {len(audio_chunk)} bytes")

        await self._simulate_transcription(msg_id, correlation_id, timestamp, audio_chunk)

    async def _simulate_transcription(
        self, msg_id: str, correlation_id: str | None, timestamp: float, audio_chunk: bytes
    ) -> None:
        """Simulate Whisper transcription result."""
        simulated_segment = {
            "segment_id": f"seg_{correlation_id[:8]}" if correlation_id else f"seg_{msg_id}",
            "text": f"[Transcribed audio chunk {msg_id}]",
            "start_time": timestamp,
            "end_time": timestamp + 0.5,
            "confidence": 0.95,
            "language": "en",
            "completed": True,
        }

        await self.stream_manager.publish_segment(simulated_segment)
        logger.debug(f"Published segment for chunk {msg_id}")


class AggregationWorker(BaseWorker):
    """
    Worker that aggregates transcription segments.

    This worker:
    1. Reads segments from segments stream
    2. Performs deduplication
    3. Updates consolidated transcript
    4. Extracts questions
    """

    def __init__(self, stream_manager: RedisStreamManager):
        super().__init__(stream_manager)
        self.unconsolidated = UnconsolidatedTranscript()
        self.consolidated = ConsolidatedTranscript()
        self.questions: dict[str, Question] = {}
        self._segment_cache: dict[str, str] = {}
        self._commit_timestamps: dict[str, float] = {}

    async def process_message(self, msg_id: str, data: dict[str, Any]) -> None:
        """Process a transcription segment."""
        segment_data = json.loads(data.get("data", "{}"))

        segment_id = segment_data.get("segment_id", msg_id)
        text = segment_data.get("text", "")
        start_time = segment_data.get("start_time", 0.0)
        end_time = segment_data.get("end_time", 0.0)
        confidence = segment_data.get("confidence", 0.0)
        language = segment_data.get("language", "en")
        is_completed = segment_data.get("completed", False)

        normalized_text = self._normalize_text(text)
        if not normalized_text:
            return

        status = SegmentStatus.COMMITTED if is_completed else SegmentStatus.FINAL

        self._update_unconsolidated(
            segment_id=segment_id,
            text=normalized_text,
            start_time=start_time,
            end_time=end_time,
            confidence=confidence,
            language=language,
            status=status,
        )

        if is_completed:
            self._update_consolidated()
            await self._extract_questions(segment_id, normalized_text, status)

        logger.debug(f"Aggregated segment {segment_id}: {normalized_text[:50]}...")

    def _normalize_text(self, text: str) -> str:
        """Normalize text for storage."""
        text = text.strip()
        import re

        text = re.sub(r"\s+", " ", text)
        return text

    def _update_unconsolidated(
        self,
        segment_id: str,
        text: str,
        start_time: float,
        end_time: float,
        confidence: float,
        language: str,
        status: SegmentStatus,
    ) -> None:
        """Update unconsolidated transcript with new segment."""
        existing = self.unconsolidated._find_segment(segment_id)

        if existing:
            if text != existing.text:
                existing.text = text
                existing.revision += 1
        else:
            segment = TranscriptSegment(
                segment_id=segment_id,
                start_time=start_time,
                end_time=end_time,
                text=text,
                status=status,
                confidence=confidence,
                revision=1,
                language=language,
                is_english=language.lower() == "en",
            )
            self.unconsolidated.add_segment(segment)
            self._segment_cache[segment_id] = text

    def _update_consolidated(self) -> None:
        """Update consolidated transcript from committed segments."""
        committed_segments = [
            s for s in self.unconsolidated.segments if s.status == SegmentStatus.COMMITTED
        ]
        self.consolidated.update_from_segments(committed_segments)

    async def _extract_questions(self, segment_id: str, text: str, status: SegmentStatus) -> None:
        """Extract questions from segment."""
        if status != SegmentStatus.COMMITTED:
            return

        if not self._is_english_question(text):
            return

        question_text = text.lower().strip()
        question_id = self._generate_question_id(question_text)

        if question_id in self.questions:
            existing = self.questions[question_id]
            if segment_id not in existing.segment_ids:
                existing.segment_ids.append(segment_id)
        else:
            question = Question(
                question_id=question_id,
                text=text,
                normalized_text=question_text,
                segment_ids=[segment_id],
                is_explicit="?" in text,
            )
            self.questions[question_id] = question

    def _is_english_question(self, text: str) -> bool:
        """Check if text is an English question."""
        english_markers = ["what", "how", "why", "when", "where", "who", "which", "?"]
        return any(marker in text.lower() for marker in english_markers)

    def _generate_question_id(self, text: str) -> str:
        """Generate a unique ID for a question."""
        import hashlib

        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def get_unconsolidated(self) -> UnconsolidatedTranscript:
        return self.unconsolidated

    def get_consolidated(self) -> ConsolidatedTranscript:
        return self.consolidated

    def get_questions(self) -> list[Question]:
        return list(self.questions.values())


class BroadcastWorker(BaseWorker):
    """
    Worker that broadcasts events to connected clients.

    This worker:
    1. Reads events from events stream
    2. Broadcasts to SSE clients
    3. Broadcasts to WebSocket clients
    """

    def __init__(self, stream_manager: RedisStreamManager):
        super().__init__(stream_manager)
        self._sse_queues: list[asyncio.Queue] = []
        self._ws_queues: list[asyncio.Queue] = []

    def add_sse_client(self, queue: asyncio.Queue) -> None:
        """Add an SSE client queue."""
        self._sse_queues.append(queue)

    def remove_sse_client(self, queue: asyncio.Queue) -> None:
        """Remove an SSE client queue."""
        if queue in self._sse_queues:
            self._sse_queues.remove(queue)

    def add_ws_client(self, queue: asyncio.Queue) -> None:
        """Add a WebSocket client queue."""
        self._ws_queues.append(queue)

    def remove_ws_client(self, queue: asyncio.Queue) -> None:
        """Remove a WebSocket client queue."""
        if queue in self._ws_queues:
            self._ws_queues.remove(queue)

    async def process_message(self, msg_id: str, data: dict[str, Any]) -> None:
        """Broadcast event to all connected clients."""
        event_data = json.loads(data.get("data", "{}"))

        await self._broadcast_sse(event_data)
        await self._broadcast_websocket(event_data)

        logger.debug(
            f"Broadcasted event {msg_id} to {len(self._sse_queues)} SSE + {len(self._ws_queues)} WS clients"
        )

    async def _broadcast_sse(self, event_data: dict[str, Any]) -> None:
        """Broadcast to SSE clients."""
        event = f"data: {json.dumps(event_data)}\n\n"
        for queue in self._sse_queues[:]:
            try:
                await asyncio.wait_for(queue.put(event), timeout=1.0)
            except TimeoutError:
                pass
            except Exception:
                self.remove_sse_client(queue)

    async def _broadcast_websocket(self, event_data: dict[str, Any]) -> None:
        """Broadcast to WebSocket clients."""
        for queue in self._ws_queues[:]:
            try:
                await asyncio.wait_for(queue.put(event_data), timeout=1.0)
            except TimeoutError:
                pass
            except Exception:
                self.remove_ws_client(queue)


class WorkerPool:
    """
    Manages a pool of workers for parallel stream processing.
    """

    def __init__(self, stream_manager: RedisStreamManager):
        self.stream_manager = stream_manager
        self.transcription_workers: list[TranscriptionWorker] = []
        self.aggregation_workers: list[AggregationWorker] = []
        self.broadcast_workers: list[BroadcastWorker] = []

    def create_transcription_workers(self, count: int = 2) -> None:
        """Create transcription workers."""
        for _ in range(count):
            worker = TranscriptionWorker(self.stream_manager)
            self.transcription_workers.append(worker)
            self.stream_manager.register_handler(StreamType.AUDIO, worker.process_message)
        logger.info(f"Created {count} transcription workers")

    def create_aggregation_workers(self, count: int = 2) -> None:
        """Create aggregation workers."""
        for _ in range(count):
            worker = AggregationWorker(self.stream_manager)
            self.aggregation_workers.append(worker)
            self.stream_manager.register_handler(StreamType.SEGMENTS, worker.process_message)
        logger.info(f"Created {count} aggregation workers")

    def create_broadcast_workers(self, count: int = 1) -> None:
        """Create broadcast workers."""
        for _ in range(count):
            worker = BroadcastWorker(self.stream_manager)
            self.broadcast_workers.append(worker)
            self.stream_manager.register_handler(StreamType.EVENTS, worker.process_message)
        logger.info(f"Created {count} broadcast workers")

    async def start_all(self) -> None:
        """Start all workers."""
        for worker in (
            self.transcription_workers + self.aggregation_workers + self.broadcast_workers
        ):
            await worker.start()

    async def stop_all(self) -> None:
        """Stop all workers."""
        for worker in (
            self.transcription_workers + self.aggregation_workers + self.broadcast_workers
        ):
            await worker.stop()

    def get_aggregator(self) -> AggregationWorker | None:
        """Get an aggregation worker for transcript retrieval."""
        return self.aggregation_workers[0] if self.aggregation_workers else None

    def get_broadcaster(self) -> BroadcastWorker | None:
        """Get a broadcast worker for client management."""
        return self.broadcast_workers[0] if self.broadcast_workers else None
