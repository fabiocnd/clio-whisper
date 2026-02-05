"""
Redis-based Pipeline for Clio Whisper.

Provides a high-performance pipeline using Redis Streams for parallel
processing of audio, transcription, aggregation, and broadcasting.

This pipeline operates independently from the legacy in-memory pipeline
and can be enabled via configuration (REDIS_ENABLED=true).
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import uuid

from loguru import logger

from clio_api_server.app.core.config import get_settings
from clio_api_server.app.models.control import PipelineState, StatusResponse
from clio_api_server.app.models.events import EventType, StreamingEvent
from clio_api_server.app.models.metrics import Metrics
from clio_api_server.app.models.transcript import TranscriptSegment
from clio_api_server.app.services.audio_capture import AudioCapture
from clio_api_server.app.services.redis_stream_manager import (
    RedisStreamManager,
    StreamType,
)
from clio_api_server.app.services.redis_workers import (
    WorkerPool,
    AggregationWorker,
    BroadcastWorker,
)


class RedisPipeline:
    """
    High-performance pipeline using Redis Streams.

    Architecture:
        Audio Input → Redis Stream → Transcription Workers → Segments Stream
                                                                ↓
        Events Stream ← Aggregation Workers ←───────────────────────
                ↓
        Broadcast Workers → SSE/WebSocket Clients
    """

    def __init__(self):
        self.settings = get_settings()
        self.state = PipelineState.STOPPED
        self._running = False

        self.stream_manager: Optional[RedisStreamManager] = None
        self.worker_pool: Optional[WorkerPool] = None

        self.audio_capture: Optional[AudioCapture] = None
        self._audio_queue: Optional[asyncio.Queue] = None

        self.metrics = Metrics()

        self._audio_task: Optional[asyncio.Task] = None
        self._whisper_task: Optional[asyncio.Task] = None
        self._consumer_task: Optional[asyncio.Task] = None

        self._sse_clients: List[asyncio.Queue] = []
        self._ws_clients: List[asyncio.Queue] = []

        self._last_error: Optional[str] = None

    async def initialize(self) -> bool:
        """Initialize Redis connection and workers."""
        try:
            self.stream_manager = RedisStreamManager()
            await self.stream_manager.connect()

            self.worker_pool = WorkerPool(self.stream_manager)
            self.worker_pool.create_transcription_workers(count=2)
            self.worker_pool.create_aggregation_workers(count=2)
            self.worker_pool.create_broadcast_workers(count=1)

            broadcaster = self.worker_pool.get_broadcaster()
            if broadcaster:
                pass

            logger.info("Redis pipeline initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Redis pipeline: {e}")
            self._last_error = str(e)
            return False

    async def start(self) -> bool:
        """Start the Redis pipeline."""
        if self.state != PipelineState.STOPPED:
            logger.warning(f"Cannot start Redis pipeline from state: {self.state}")
            return False

        if not self.stream_manager:
            success = await self.initialize()
            if not success:
                return False

        logger.info("Starting Redis pipeline")
        self.state = PipelineState.STARTING
        self._last_error = None

        self._audio_queue = asyncio.Queue(maxsize=100)
        self.audio_capture = AudioCapture(audio_queue=self._audio_queue)

        try:
            await self.stream_manager.start_consumers()
            await self.worker_pool.start_all()

            self._audio_task = asyncio.create_task(self._audio_capture_loop())
            self._whisper_task = asyncio.create_task(self._whisper_publisher_loop())

            await asyncio.sleep(1.0)

            if self.audio_capture.is_running():
                self.state = PipelineState.RUNNING
                self._running = True
                logger.info("Redis pipeline started successfully")
                return True
            else:
                self.state = PipelineState.DEGRADED
                logger.warning("Redis pipeline started in degraded mode")
                return True

        except Exception as e:
            logger.error(f"Failed to start Redis pipeline: {e}")
            self._last_error = str(e)
            self.state = PipelineState.ERROR
            return False

    async def stop(self) -> None:
        """Stop the Redis pipeline."""
        if self.state == PipelineState.STOPPED:
            return

        logger.info("Stopping Redis pipeline")
        self.state = PipelineState.STOPPING
        self._running = False

        if self.audio_capture:
            self.audio_capture.stop()

        for task in [self._audio_task, self._whisper_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self.stream_manager:
            await self.stream_manager.stop_consumers()
            await self.worker_pool.stop_all()
            await self.stream_manager.disconnect()

        self._update_metrics()
        self.state = PipelineState.STOPPED
        logger.info("Redis pipeline stopped")

    async def _audio_capture_loop(self) -> None:
        """Capture audio and publish to Redis stream."""
        try:
            await self.audio_capture.start()
        except Exception as e:
            logger.error(f"Audio capture error: {e}")
            self._last_error = str(e)
            self.state = PipelineState.ERROR

    async def _whisper_publisher_loop(self) -> None:
        """Publish audio chunks to Redis stream for transcription."""
        while self._running:
            try:
                if self._audio_queue and not self._audio_queue.empty():
                    audio_data = await self._audio_queue.get()

                    metadata = {
                        "device_index": self.settings.audio_device_index,
                        "sample_rate": self.settings.audio_sample_rate,
                        "channels": self.settings.audio_channels,
                    }

                    await self.stream_manager.publish_audio(audio_data, metadata)
                    self.metrics.audio_frames_sent += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Whisper publisher error: {e}")
                await asyncio.sleep(0.1)

    def add_sse_client(self) -> asyncio.Queue:
        """Add an SSE client for event broadcasting."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._sse_clients.append(queue)

        if self.worker_pool:
            broadcaster = self.worker_pool.get_broadcaster()
            if broadcaster:
                broadcaster.add_sse_client(queue)

        return queue

    def remove_sse_client(self, queue: asyncio.Queue) -> None:
        """Remove an SSE client."""
        if queue in self._sse_clients:
            self._sse_clients.remove(queue)

        if self.worker_pool:
            broadcaster = self.worker_pool.get_broadcaster()
            if broadcaster:
                broadcaster.remove_sse_client(queue)

    def add_ws_client(self) -> asyncio.Queue:
        """Add a WebSocket client for event broadcasting."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._ws_clients.append(queue)

        if self.worker_pool:
            broadcaster = self.worker_pool.get_broadcaster()
            if broadcaster:
                broadcaster.add_ws_client(queue)

        return queue

    def remove_ws_client(self, queue: asyncio.Queue) -> None:
        """Remove a WebSocket client."""
        if queue in self._ws_clients:
            self._ws_clients.remove(queue)

        if self.worker_pool:
            broadcaster = self.worker_pool.get_broadcaster()
            if broadcaster:
                broadcaster.remove_ws_client(queue)

    def _update_metrics(self) -> None:
        """Update pipeline metrics."""
        self.metrics.audio_queue_depth = self._audio_queue.qsize() if self._audio_queue else 0
        self.metrics.connected_sse_clients = len(self._sse_clients)
        self.metrics.connected_ws_clients = len(self._ws_clients)

        aggregator = self.worker_pool.get_aggregator()
        if aggregator:
            self.metrics.segments_committed = len(
                [s for s in aggregator.unconsolidated.segments if s.status.value == "committed"]
            )
            self.metrics.questions_extracted = len(aggregator.questions)

        if self.stream_manager:
            self.metrics.reconnect_count = len(self.stream_manager.get_stats())

    def get_status(self) -> StatusResponse:
        """Get current pipeline status."""
        self._update_metrics()

        ws_status = (
            "connected"
            if self.stream_manager and self.stream_manager.is_connected()
            else "disconnected"
        )

        audio_device = None
        sample_rate = 0
        if self.audio_capture and self.audio_capture._device_info:
            audio_device = self.audio_capture._device_info.get("name")
            sample_rate = self.settings.audio_sample_rate

        return StatusResponse(
            state=self.state,
            audio_device=audio_device,
            sample_rate=sample_rate,
            ws_connection=ws_status,
            queue_depths=self.metrics.to_dict(),
            last_error=self._last_error,
        )

    def get_metrics(self) -> Metrics:
        """Get pipeline metrics."""
        self._update_metrics()
        return self.metrics

    def get_unconsolidated_transcript(self):
        """Get unconsolidated transcript from aggregator."""
        aggregator = self.worker_pool.get_aggregator()
        if aggregator:
            return aggregator.get_unconsolidated()
        return None

    def get_consolidated_transcript(self):
        """Get consolidated transcript from aggregator."""
        aggregator = self.worker_pool.get_aggregator()
        if aggregator:
            return aggregator.get_consolidated()
        return None

    def get_questions(self):
        """Get extracted questions from aggregator."""
        aggregator = self.worker_pool.get_aggregator()
        if aggregator:
            return aggregator.get_questions()
        return []

    async def get_health(self) -> Dict[str, Any]:
        """Get health status."""
        if not self.stream_manager:
            return {"healthy": False, "error": "Not initialized"}

        return await self.stream_manager.health_check()

    def reset(self) -> None:
        """Reset pipeline state."""
        self.state = PipelineState.STOPPED
        self._running = False
        self.metrics = Metrics()
        self._sse_clients.clear()
        self._ws_clients.clear()

        if self.stream_manager:
            asyncio.create_task(self.stream_manager.cleanup_streams())
