import asyncio
import json
import time
from typing import Any, Callable, Optional

import websockets
from loguru import logger

from clio_api_server.app.core.config import WhisperLiveConfig, get_settings
from clio_api_server.app.models.events import WhisperLiveEvent, StreamingEvent


class WhisperLiveClient:
    END_OF_AUDIO = "END_OF_AUDIO"

    def __init__(
        self,
        config: Optional[WhisperLiveConfig] = None,
        event_callback: Optional[Callable[[StreamingEvent], None]] = None,
    ):
        self.config = config or get_settings().whisperlive
        self.event_callback = event_callback
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._base_reconnect_delay = 1.0
        self._connected = False
        self._backend: Optional[str] = None
        self._messages_sent = 0
        self._messages_received = 0

    def register_event_callback(self, callback: Callable[[StreamingEvent], None]) -> None:
        self.event_callback = callback

    def _create_config_message(self) -> dict:
        return {
            "uid": self.config.uid,
            "language": self.config.language,
            "task": self.config.task,
            "model": self.config.model,
            "use_vad": self.config.use_vad,
            "send_last_n_segments": self.config.send_last_n_segments,
        }

    async def _connect(self) -> bool:
        try:
            ws_url = f"ws://{self.config.host}:{self.config.port}"
            logger.info(f"Connecting to WhisperLive at {ws_url}")
            self._websocket = await asyncio.wait_for(
                websockets.connect(ws_url, close_timeout=10),
                timeout=10.0,
            )
            logger.info("WebSocket connection established")
            return True
        except asyncio.TimeoutError:
            logger.error("Connection timeout")
            return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def _send_config(self) -> bool:
        try:
            config_msg = self._create_config_message()
            await self._websocket.send(json.dumps(config_msg))
            self._messages_sent += 1
            logger.info(f"Sent config: {json.dumps(config_msg)}")
            return True
        except Exception as e:
            logger.error(f"Failed to send config: {e}")
            return False

    async def _wait_for_ready(self) -> bool:
        try:
            while self._running:
                message = await asyncio.wait_for(
                    self._websocket.recv(),
                    timeout=30.0,
                )
                self._messages_received += 1
                event = self._parse_message(message)
                if event:
                    await self._handle_event(event)
                    if event.message == "SERVER_READY":
                        logger.info(f"Server ready with backend: {event.backend}")
                        self._backend = event.backend
                        return True
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for SERVER_READY")
        except Exception as e:
            logger.error(f"Error waiting for ready: {e}")
        return False

    def _parse_message(self, message: str) -> Optional[WhisperLiveEvent]:
        try:
            data = json.loads(message)
            return WhisperLiveEvent(**data)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON message: {message[:100]}")
            return None
        except Exception as e:
            logger.error(f"Failed to parse message: {e}")
            return None

    async def _handle_event(self, event: WhisperLiveEvent) -> None:
        if self.event_callback:
            streaming_events = StreamingEvent.from_whisper_event(event)
            for se in streaming_events:
                self.event_callback(se)

    async def _audio_sender(self, audio_queue: asyncio.Queue) -> None:
        logger.info("Starting audio sender task")
        while self._running:
            try:
                audio_data = await asyncio.wait_for(
                    audio_queue.get(),
                    timeout=5.0,
                )
                if not self._running:
                    break
                if self._websocket and self._connected:
                    await self._websocket.send(audio_data)
                    self._messages_sent += 1
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed during audio send")
                break
            except Exception as e:
                logger.error(f"Audio send error: {e}")
                break
        logger.info("Audio sender task stopped")

    async def _event_receiver(self) -> None:
        logger.info("Starting event receiver task")
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._websocket.recv(),
                    timeout=30.0,
                )
                self._messages_received += 1
                event = self._parse_message(message)
                if event:
                    await self._handle_event(event)
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
                break
            except Exception as e:
                logger.error(f"Event receiver error: {e}")
                break
        logger.info("Event receiver task stopped")

    async def _calculate_reconnect_delay(self) -> float:
        delay = self._base_reconnect_delay * (2 ** self._reconnect_attempts)
        import random
        jitter = delay * 0.1 * random.random()
        return min(delay + jitter, 30.0)

    async def connect(self, audio_queue: asyncio.Queue) -> bool:
        if not await self._connect():
            return False

        if not await self._send_config():
            return False

        if not await self._wait_for_ready():
            return False

        self._running = True
        self._connected = True
        self._reconnect_attempts = 0

        asyncio.create_task(self._audio_sender(audio_queue))
        asyncio.create_task(self._event_receiver())

        return True

    async def reconnect(self, audio_queue: asyncio.Queue) -> bool:
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            return False

        delay = await self._calculate_reconnect_delay()
        logger.info(f"Reconnecting in {delay:.2f}s (attempt {self._reconnect_attempts})")
        await asyncio.sleep(delay)

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
        self._websocket = None

        self._connected = False
        success = await self.connect(audio_queue)
        if success:
            logger.info("Reconnect successful")
        return success

    async def send_end_of_audio(self) -> None:
        if self._websocket and self._connected:
            try:
                await self._websocket.send(self.END_OF_AUDIO)
                self._messages_sent += 1
                logger.info("Sent END_OF_AUDIO signal")
            except Exception as e:
                logger.error(f"Failed to send END_OF_AUDIO: {e}")

    async def close(self) -> None:
        self._running = False
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None
        self._connected = False
        logger.info("WebSocket connection closed")

    def is_connected(self) -> bool:
        return self._connected

    def get_stats(self) -> dict:
        return {
            "connected": self._connected,
            "backend": self._backend,
            "messages_sent": self._messages_sent,
            "messages_received": self._messages_received,
            "reconnect_attempts": self._reconnect_attempts,
        }

    def reset_stats(self) -> None:
        self._messages_sent = 0
        self._messages_received = 0
        self._reconnect_attempts = 0
