import asyncio
import json
import uuid
from typing import Any, Callable, Optional

import numpy as np
import websockets
from loguru import logger

from clio_api_server.app.core.config import get_settings


class WhisperLiveClient:
    END_OF_AUDIO = "END_OF_AUDIO"

    def __init__(
        self,
        event_callback: Optional[Callable[[Any], None]] = None,
    ):
        self.settings = get_settings()
        self.event_callback = event_callback
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._base_reconnect_delay = 1.0
        self._connected = False
        self._backend = None
        self._messages_sent = 0
        self._messages_received = 0
        self._waiting = False

    def register_event_callback(self, callback: Callable[[Any], None]) -> None:
        self.event_callback = callback

    def _create_config_message(self) -> dict:
        return {
            "uid": str(uuid.uuid4()),
            "language": self.settings.whisperlive_language,
            "task": self.settings.whisperlive_task,
            "model": self.settings.whisperlive_model,
            "use_vad": self.settings.whisperlive_use_vad,
            "send_last_n_segments": self.settings.whisperlive_send_last_n_segments,
        }

    async def _connect(self) -> bool:
        try:
            ws_url = f"ws://{self.settings.whisperlive_host}:{self.settings.whisperlive_port}"
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
            config_str = json.dumps(config_msg)
            logger.info(f"Sending config: {config_str}")
            await self._websocket.send(config_str)
            self._messages_sent += 1
            logger.info("Config sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send config: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def _wait_for_ready(self) -> bool:
        try:
            logger.info("Waiting for SERVER_READY...")
            while True:
                message = await asyncio.wait_for(
                    self._websocket.recv(),
                    timeout=30.0,
                )
                self._messages_received += 1
                logger.info(f"Received: {message[:200]}")

                if isinstance(message, bytes):
                    logger.warning(f"Received binary data, skipping")
                    continue

                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message[:100]}")
                    continue

                if self.event_callback:
                    self.event_callback(event)

                if event.get("status") == "WAIT":
                    logger.warning(f"Server busy, wait time: {event.get('message')} minutes")
                    self._waiting = True
                    return False

                if event.get("message") == "SERVER_READY":
                    logger.info(f"SERVER_READY with backend: {event.get('backend')}")
                    self._backend = event.get("backend")
                    self._connected = True
                    return True

        except asyncio.TimeoutError:
            logger.error("Timeout waiting for SERVER_READY")
        except Exception as e:
            logger.error(f"Error waiting for ready: {e}")
            import traceback

            traceback.print_exc()
        return False

    async def _audio_sender(self, audio_queue: asyncio.Queue) -> None:
        logger.info("Audio sender task started")
        audio_format = self.settings.whisperlive_audio_format

        while self._running:
            try:
                audio_data = await asyncio.wait_for(
                    audio_queue.get(),
                    timeout=5.0,
                )
                if not self._running:
                    break
                if self._websocket and self._connected:
                    if audio_format == "float32":
                        audio_array = (
                            np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
                        )
                        await self._websocket.send(audio_array.tobytes())
                    else:
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
        print(
            f"[WS] Event receiver started. Callback registered: {self.event_callback is not None}"
        )
        logger.info("Event receiver task started")
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._websocket.recv(),
                    timeout=30.0,
                )
                self._messages_received += 1

                if isinstance(message, bytes):
                    continue

                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {message[:100]}")
                    continue

                if self.event_callback:
                    try:
                        self.event_callback(event)
                    except Exception as cb_err:
                        logger.error(f"Callback error: {cb_err}")

                if event.get("message") == "DISCONNECT":
                    logger.warning("Server disconnected")
                    self._connected = False
                    break

            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"Connection closed: {e}")
                self._connected = False
                break
            except Exception as e:
                logger.error(f"Event receiver error: {e}")
                break
        logger.info("Event receiver task stopped")

    async def connect(self, audio_queue: asyncio.Queue) -> bool:
        logger.info("WhisperLiveClient.connect: Starting connection")

        self._running = True
        self._connected = False
        self._waiting = False

        if not await self._connect():
            logger.error("Failed to connect")
            self._running = False
            return False

        if not await self._send_config():
            await self._websocket.close()
            self._running = False
            return False

        if not await self._wait_for_ready():
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._running = False
            return False

        logger.info("WhisperLiveClient: Connected successfully")
        self._reconnect_attempts = 0

        asyncio.create_task(self._audio_sender(audio_queue))
        asyncio.create_task(self._event_receiver())

        return True

    async def reconnect(self, audio_queue: asyncio.Queue) -> bool:
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            return False

        delay = self._base_reconnect_delay * (2 ** (self._reconnect_attempts - 1))
        import random

        jitter = delay * random.uniform(0.8, 1.2)
        delay = min(delay + jitter, 30.0)

        logger.info(f"Reconnecting in {delay:.2f}s (attempt {self._reconnect_attempts})")
        await asyncio.sleep(delay)

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
        self._websocket = None
        self._connected = False

        return await self.connect(audio_queue)

    def is_connected(self) -> bool:
        return self._connected and self._running

    def was_waiting(self) -> bool:
        return self._waiting

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
