import asyncio
import wave
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import sounddevice as sd
from loguru import logger

from clio_api_server.app.core.config import get_settings


class AudioCapture:
    def __init__(
        self,
        audio_queue: Optional[asyncio.Queue] = None,
    ):
        self.settings = get_settings()
        self.audio_queue = audio_queue or asyncio.Queue(maxsize=100)
        self._running = False
        self._stream: Optional[sd.InputStream] = None
        self._device_info: Optional[dict] = None
        self._audio_file: Optional[wave.Wave_read] = None
        self._frame_count = 0
        self._dropped_frames = 0
        self._callbacks: list[Callable[[str, Any], None]] = []

    def register_callback(self, callback: Callable[[str, Any], None]) -> None:
        self._callbacks.append(callback)

    def _emit(self, event: str, data: Any) -> None:
        for cb in self._callbacks:
            try:
                cb(event, data)
            except Exception:
                pass

    def get_available_devices(self) -> list[dict]:
        devices = []
        try:
            for idx, info in enumerate(sd.query_devices()):
                if info["max_input_channels"] > 0:
                    devices.append({
                        "index": idx,
                        "name": info["name"],
                        "channels": info["max_input_channels"],
                        "default_samplerate": info["default_samplerate"],
                    })
        except Exception as e:
            logger.error(f"Failed to query audio devices: {e}")
        return devices

    def select_device(self) -> int:
        if self.settings.audio_device_index >= 0:
            return self.settings.audio_device_index
        if self.settings.audio_device_name:
            for idx, info in enumerate(sd.query_devices()):
                if self.settings.audio_device_name.lower() in info["name"].lower():
                    logger.info(f"Selected device by name: {info['name']}")
                    return idx
        try:
            default_device = sd.default.device[0]
            logger.info(f"Using default device: {default_device}")
            return default_device
        except Exception:
            logger.warning("No default device found, using first available")
            for idx, info in enumerate(sd.query_devices()):
                if info["max_input_channels"] > 0:
                    return idx
        raise RuntimeError("No audio input device available")

    async def _capture_microphone(self) -> None:
        self._running = True
        device_index = self.select_device()
        self._device_info = sd.query_devices(device_index)
        logger.info(f"Starting audio capture on device: {self._device_info['name']}")

        loop = asyncio.get_event_loop()

        def audio_callback(indata: np.ndarray, frames: int, time: Any, status: Any) -> None:
            if not self._running:
                return
            audio_data = indata.tobytes()
            try:
                loop.call_soon_threadsafe(
                    lambda: self.audio_queue.put_nowait(audio_data)
                )
                self._frame_count += 1
            except asyncio.QueueFull:
                self._dropped_frames += 1
                logger.warning(f"Audio queue full, dropping frame {self._frame_count}")

        self._stream = sd.InputStream(
            device=device_index,
            samplerate=self.settings.audio_sample_rate,
            channels=self.settings.audio_channels,
            dtype="int16",
            blocksize=self.settings.audio_chunk_size,
            callback=audio_callback,
        )

        self._stream.start()
        try:
            while self._running:
                await asyncio.sleep(0.1)
        finally:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.info(f"Audio capture stopped. Frames captured: {self._frame_count}")

    async def _capture_file(self) -> None:
        file_path = Path(self.settings.audio_input_file)
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        logger.info(f"Starting audio capture from file: {file_path}")
        self._audio_file = wave.open(str(file_path), "rb")
        self._running = True

        chunk_size = self.settings.audio_chunk_size * self.settings.audio_channels * 2
        while self._running:
            audio_data = self._audio_file.readframes(chunk_size // 2)
            if not audio_data:
                logger.info("End of audio file reached")
                break
            try:
                await asyncio.wait_for(
                    self.audio_queue.put(audio_data),
                    timeout=1.0,
                )
                self._frame_count += 1
            except asyncio.TimeoutError:
                self._dropped_frames += 1
                logger.warning("Audio queue timeout, dropping frame")
            await asyncio.sleep(0.001)

        self._audio_file.close()
        self._audio_file = None
        logger.info(f"File audio capture stopped. Frames read: {self._frame_count}")

    async def start(self) -> None:
        self._frame_count = 0
        self._dropped_frames = 0
        if self.settings.audio_input_mode == "file":
            await self._capture_file()
        else:
            await self._capture_microphone()

    def stop(self) -> None:
        self._running = False
        if self._stream:
            try:
                self._stream.abort()
            except Exception:
                pass
        if self._audio_file:
            try:
                self._audio_file.close()
            except Exception:
                pass

    def get_stats(self) -> dict:
        return {
            "frames_captured": self._frame_count,
            "frames_dropped": self._dropped_frames,
            "queue_size": self.audio_queue.qsize(),
            "device": self._device_info.get("name") if self._device_info else None,
        }

    def is_running(self) -> bool:
        return self._running
