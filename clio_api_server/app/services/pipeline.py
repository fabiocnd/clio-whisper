import asyncio
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from clio_api_server.app.core.config import get_settings
from clio_api_server.app.models.control import PipelineState, StatusResponse
from clio_api_server.app.models.events import EventType, StreamingEvent
from clio_api_server.app.models.metrics import Metrics
from clio_api_server.app.services.audio_capture import AudioCapture
from clio_api_server.app.services.transcript_aggregator import TranscriptAggregator
from clio_api_server.app.services.whisperlive_client import WhisperLiveClient


class Pipeline:
    def __init__(self):
        self.settings = get_settings()
        self.state = PipelineState.STOPPED

        self.audio_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        self.audio_capture = AudioCapture(audio_queue=self.audio_queue)
        self.whisper_client = WhisperLiveClient()
        self.aggregator = TranscriptAggregator()

        self.metrics = Metrics()

        self._audio_task: Optional[asyncio.Task] = None
        self._client_task: Optional[asyncio.Task] = None
        self._aggregator_task: Optional[asyncio.Task] = None
        self._sse_clients: List[asyncio.Queue] = []
        self._ws_clients: List[asyncio.Queue] = []

        self._last_error: Optional[str] = None

        self._setup_callbacks()

    def _setup_callbacks(self) -> None:
        self.whisper_client.register_event_callback(self._on_whisper_event)
        self.aggregator.register_event_callback(self._on_aggregator_event)

    async def _on_whisper_event(self, event: StreamingEvent) -> None:
        try:
            await self.event_queue.put(event)
        except asyncio.QueueFull:
            self.metrics.segments_dropped += 1
            logger.warning("Event queue full, dropping event")

    async def _on_aggregator_event(self, event: StreamingEvent) -> None:
        await self._broadcast_event(event)

    async def _broadcast_event(self, event: StreamingEvent) -> None:
        sse_clients = self._sse_clients[:]
        ws_clients = self._ws_clients[:]

        for client_queue in sse_clients:
            try:
                await asyncio.wait_for(client_queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

        for client_queue in ws_clients:
            try:
                await asyncio.wait_for(client_queue.put(event), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

    async def _audio_capture_loop(self) -> None:
        try:
            await self.audio_capture.start()
        except Exception as e:
            logger.error(f"Audio capture error: {e}")
            self._last_error = str(e)
            self.state = PipelineState.ERROR

    async def _whisper_client_loop(self) -> None:
        connected = False
        while self.state in (PipelineState.STARTING, PipelineState.RUNNING):
            try:
                if not connected:
                    connected = await self.whisper_client.connect(self.audio_queue)
                    if connected:
                        self.metrics.reconnect_count += 1
                        logger.info("Connected to WhisperLive")
                    else:
                        await asyncio.sleep(2.0)
                        continue

                await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                logger.info("Whisper client task cancelled")
                break
            except Exception as e:
                logger.error(f"Whisper client error: {e}")
                self._last_error = str(e)
                connected = False
                if self.state == PipelineState.RUNNING:
                    if await self.whisper_client.reconnect(self.audio_queue):
                        connected = True

        if self.whisper_client.is_connected():
            await self.whisper_client.close()

    async def _aggregator_loop(self) -> None:
        while self.state in (PipelineState.STARTING, PipelineState.RUNNING):
            try:
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                await self.aggregator.process_event(event)

                if event.event_type == EventType.FINAL:
                    self.metrics.segments_received += 1
                elif event.event_type == EventType.PARTIAL:
                    self.metrics.segments_received += 1

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                logger.info("Aggregator task cancelled")
                break
            except Exception as e:
                logger.error(f"Aggregator error: {e}")
                self._last_error = str(e)

    def _update_metrics(self) -> None:
        self.metrics.audio_queue_depth = self.audio_queue.qsize()
        self.metrics.event_queue_depth = self.event_queue.qsize()
        self.metrics.connected_sse_clients = len(self._sse_clients)
        self.metrics.connected_ws_clients = len(self._ws_clients)
        self.metrics.segments_committed = len(
            [s for s in self.aggregator.unconsolidated.segments
             if s.status.value == "committed"]
        )
        self.metrics.questions_extracted = len(self.aggregator.questions)

    async def start(self) -> bool:
        if self.state != PipelineState.STOPPED:
            logger.warning(f"Cannot start from state: {self.state}")
            return False

        logger.info("Starting pipeline")
        self.state = PipelineState.STARTING
        self._last_error = None

        self._audio_task = asyncio.create_task(self._audio_capture_loop())
        self._client_task = asyncio.create_task(self._whisper_client_loop())
        self._aggregator_task = asyncio.create_task(self._aggregator_loop())

        await asyncio.sleep(1.0)

        if self.audio_capture.is_running():
            self.state = PipelineState.RUNNING
            logger.info("Pipeline started successfully")
            return True
        else:
            self.state = PipelineState.DEGRADED
            logger.warning("Pipeline started in degraded mode")
            return True

    async def stop(self) -> None:
        if self.state == PipelineState.STOPPED:
            return

        logger.info("Stopping pipeline")
        self.state = PipelineState.STOPPING

        if self.whisper_client.is_connected():
            try:
                await self.whisper_client.send_end_of_audio()
            except Exception:
                pass
            await self.whisper_client.close()

        self.audio_capture.stop()

        for task in [self._audio_task, self._client_task, self._aggregator_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._update_metrics()
        self.state = PipelineState.STOPPED
        logger.info("Pipeline stopped")

    def add_sse_client(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._sse_clients.append(queue)
        return queue

    def remove_sse_client(self, queue: asyncio.Queue) -> None:
        if queue in self._sse_clients:
            self._sse_clients.remove(queue)

    def add_ws_client(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._ws_clients.append(queue)
        return queue

    def remove_ws_client(self, queue: asyncio.Queue) -> None:
        if queue in self._ws_clients:
            self._ws_clients.remove(queue)

    def get_status(self) -> StatusResponse:
        self._update_metrics()

        audio_device = None
        sample_rate = 0
        if self.audio_capture._device_info:
            audio_device = self.audio_capture._device_info.get("name")
            sample_rate = self.settings.audio.sample_rate

        ws_status = "connected" if self.whisper_client.is_connected() else "disconnected"

        if self.state == PipelineState.ERROR:
            return StatusResponse(
                state=PipelineState.ERROR,
                audio_device=audio_device,
                sample_rate=sample_rate,
                ws_connection=ws_status,
                queue_depths=self.metrics.to_dict(),
                last_error=self._last_error,
            )

        return StatusResponse(
            state=self.state,
            audio_device=audio_device,
            sample_rate=sample_rate,
            ws_connection=ws_status,
            queue_depths=self.metrics.to_dict(),
            last_error=self._last_error,
        )

    def get_metrics(self) -> Metrics:
        self._update_metrics()
        return self.metrics

    def reset(self) -> None:
        self.aggregator.reset()
        self.metrics = Metrics()
        self.audio_queue = asyncio.Queue(maxsize=200)
        self.event_queue = asyncio.Queue(maxsize=200)
        self.audio_capture = AudioCapture(audio_queue=self.audio_queue)
        self._setup_callbacks()
