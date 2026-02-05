"""
Redis Stream Manager for Clio Whisper.

Provides high-performance message streaming using Redis Streams with
consumer groups for parallel processing of audio, transcription, and events.

Architecture:
    Audio Stream (cg-transcription) ──▶ Segments Stream (cg-aggregation) ──▶ Events Stream (cg-broadcast)

Streams:
    - {prefix}:audio: Audio chunks for transcription
    - {prefix}:segments: Transcribed segments for aggregation
    - {prefix}:events: Final events for broadcasting

Consumer Groups:
    - cg-transcription: Processes audio → segments (2 workers)
    - cg-aggregation: Processes segments → consolidated (2 workers)
    - cg-sse: Broadcasts to SSE clients (1 worker)
    - cg-websocket: Broadcasts to WebSocket clients (1 worker)
"""

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any

import redis.asyncio as redis
from loguru import logger
from redis.asyncio.client import PubSub

from clio_api_server.app.core.config import get_settings


class StreamType(Enum):
    AUDIO = "audio"
    SEGMENTS = "segments"
    EVENTS = "events"


@dataclass
class StreamConfig:
    name: str
    consumer_group: str
    max_length: int = 10000
    consumers: int = 1


@dataclass
class StreamMessage:
    id: str
    stream: StreamType
    data: dict[str, Any]
    created_at: float

    def to_json(self) -> str:
        return json.dumps({"id": self.id, "stream": self.stream.value, "data": self.data})

    @classmethod
    def from_json(cls, json_str: str) -> "StreamMessage":
        parsed = json.loads(json_str)
        return cls(
            id=parsed["id"],
            stream=StreamType(parsed["stream"]),
            data=parsed["data"],
            created_at=parsed.get("created_at", time.time()),
        )


@dataclass
class ConsumerStats:
    messages_processed: int = 0
    messages_acked: int = 0
    messages_nacked: int = 0
    last_processed_at: float | None = None
    current_lag: int = 0


class RedisConnectionError(Exception):
    """Raised when Redis connection fails."""

    pass


class RedisStreamManager:
    """
    Manages Redis Streams for Clio Whisper pipeline.

    Provides pub/sub semantics with consumer groups for parallel processing.
    Supports graceful shutdown and automatic reconnection.
    """

    def __init__(self):
        self.settings = get_settings()
        self._redis: redis.Redis | None = None
        self._pubsub: PubSub | None = None
        self._running: bool = False
        self._streams: dict[StreamType, StreamConfig] = {}
        self._consumer_tasks: set[asyncio.Task] = set()
        self._message_handlers: dict[StreamType, Callable] = {}

        self._stats: dict[str, ConsumerStats] = {}

        self._setup_streams()

    def _setup_streams(self) -> None:
        prefix = self.settings.redis_stream_prefix
        self._streams = {
            StreamType.AUDIO: StreamConfig(
                name=f"{prefix}:audio",
                max_length=10000,
                consumer_group=f"{prefix}:cg-transcription",
                consumers=2,
            ),
            StreamType.SEGMENTS: StreamConfig(
                name=f"{prefix}:segments",
                max_length=10000,
                consumer_group=f"{prefix}:cg-aggregation",
                consumers=2,
            ),
            StreamType.EVENTS: StreamConfig(
                name=f"{prefix}:events",
                max_length=10000,
                consumer_group=f"{prefix}:cg-broadcast",
                consumers=1,
            ),
        }

    async def connect(self) -> None:
        """Establish connection to Redis."""
        try:
            self._redis = redis.Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                db=self.settings.redis_db,
                password=self.settings.redis_password,
                max_connections=self.settings.redis_max_connections,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info(
                f"Connected to Redis at {self.settings.redis_host}:{self.settings.redis_port}"
            )
            await self._setup_streams_and_groups()
        except redis.RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise RedisConnectionError(f"Redis connection failed: {e}") from e

    async def _setup_streams_and_groups(self) -> None:
        """Create streams and consumer groups if they don't exist."""
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        for _stream_type, config in self._streams.items():
            try:
                await self._redis.xadd(config.name, {"init": "1"}, maxlen=1, approximate=True)
                logger.debug(f"Stream {config.name} ensured")

                try:
                    await self._redis.xgroup_create(
                        config.name,
                        config.consumer_group,
                        id="0",
                        mkstream=True,
                    )
                    logger.info(
                        f"Consumer group {config.consumer_group} created for stream {config.name}"
                    )
                except redis.ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        logger.debug(f"Consumer group {config.consumer_group} already exists")
                    else:
                        raise
            except redis.RedisError as e:
                logger.error(f"Failed to setup stream {config.name}: {e}")
                raise

    async def disconnect(self) -> None:
        """Close Redis connection and cancel consumer tasks."""
        self._running = False

        for task in self._consumer_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._consumer_tasks.clear()

        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        logger.info("Redis connection closed")

    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._redis is not None and self._running

    def register_handler(self, stream_type: StreamType, handler: Callable) -> None:
        """
        Register a message handler for a stream type.

        Args:
            stream_type: Type of stream to handle
            handler: Async function that processes messages
        """
        self._message_handlers[stream_type] = handler
        logger.info(f"Registered handler for stream {stream_type.value}")

    async def publish_audio(self, audio_chunk: bytes, metadata: dict[str, Any]) -> str:
        """
        Publish audio chunk to the audio stream.

        Args:
            audio_chunk: Raw audio bytes
            metadata: Additional metadata (timestamp, device info, etc.)

        Returns:
            Message ID from Redis
        """
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        stream = self._streams[StreamType.AUDIO]
        message_id = await self._redis.xadd(
            stream.name,
            {
                "audio": audio_chunk.hex(),
                "timestamp": str(time.time()),
                "correlation_id": str(uuid.uuid4()),
                **metadata,
            },
            maxlen=stream.max_length,
            approximate=True,
        )
        logger.debug(f"Published audio chunk: {message_id}")
        return message_id

    async def publish_segment(self, segment_data: dict[str, Any]) -> str:
        """
        Publish transcribed segment to the segments stream.

        Args:
            segment_data: Segment information (text, start, end, etc.)

        Returns:
            Message ID from Redis
        """
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        stream = self._streams[StreamType.SEGMENTS]
        message_id = await self._redis.xadd(
            stream.name,
            {
                "data": json.dumps(segment_data),
                "timestamp": str(time.time()),
                "correlation_id": str(uuid.uuid4()),
            },
            maxlen=stream.max_length,
            approximate=True,
        )
        return message_id

    async def publish_event(self, event_data: dict[str, Any]) -> str:
        """
        Publish final event to the events stream.

        Args:
            event_data: Event information

        Returns:
            Message ID from Redis
        """
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        stream = self._streams[StreamType.EVENTS]
        message_id = await self._redis.xadd(
            stream.name,
            {
                "data": json.dumps(event_data),
                "timestamp": str(time.time()),
                "correlation_id": str(uuid.uuid4()),
            },
            maxlen=stream.max_length,
            approximate=True,
        )
        return message_id

    async def start_consumers(self) -> None:
        """Start consumer workers for all registered stream types."""
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        self._running = True

        for stream_type, config in self._streams.items():
            if stream_type not in self._message_handlers:
                logger.warning(f"No handler registered for stream {stream_type.value}")
                continue

            for i in range(config.consumers):
                consumer_name = f"{config.consumer_group}-worker-{i}"
                self._stats[consumer_name] = ConsumerStats()

                task = asyncio.create_task(
                    self._consumer_loop(
                        stream_type=stream_type,
                        stream_name=config.name,
                        consumer_group=config.consumer_group,
                        consumer_name=consumer_name,
                    )
                )
                self._consumer_tasks.add(task)
                logger.info(f"Started consumer {consumer_name} for stream {config.name}")

    async def _consumer_loop(
        self,
        stream_type: StreamType,
        stream_name: str,
        consumer_group: str,
        consumer_name: str,
    ) -> None:
        """Main consumer loop for a stream."""
        handler = self._message_handlers.get(stream_type)
        if not handler:
            return

        stats = self._stats[consumer_name]

        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream_name: ">"},
                    count=10,
                    block=1000,
                )

                for msg_id, data in messages:
                    try:
                        await handler(msg_id, data)
                        await self._redis.xack(stream_name, consumer_group, msg_id)
                        stats.messages_acked += 1
                        stats.messages_processed += 1
                        stats.last_processed_at = time.time()
                    except Exception as e:
                        logger.error(f"Error processing message {msg_id}: {e}")
                        stats.messages_nacked += 1
                        await self._redis.xack(stream_name, consumer_group, msg_id)

            except asyncio.CancelledError:
                logger.info(f"Consumer {consumer_name} cancelled")
                break
            except redis.RedisError as e:
                logger.error(f"Redis error in consumer {consumer_name}: {e}")
                await asyncio.sleep(1)

        logger.info(f"Consumer {consumer_name} stopped")

    async def get_stream_info(self, stream_type: StreamType) -> dict[str, Any]:
        """Get information about a stream."""
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        config = self._streams[stream_type]
        info = await self._redis.xinfo_stream(config.name)
        groups = await self._redis.xinfo_groups(config.name)

        return {
            "stream": config.name,
            "length": info.get("length", 0),
            "consumer_groups": [
                {
                    "name": g.get("name"),
                    "consumers": g.get("consumers", 0),
                    "pending": g.get("pending", 0),
                    "last_delivered": g.get("last-delivered-id"),
                }
                for g in groups
            ],
        }

    async def get_consumer_lag(self, stream_type: StreamType) -> dict[str, int]:
        """Get lag information for consumer groups."""
        if not self._redis:
            raise RedisConnectionError("Redis not connected")

        config = self._streams[stream_type]
        groups = await self._redis.xinfo_groups(config.name)

        lag_info = {}
        for group in groups:
            group_name = group.get("name")
            pending = group.get("pending", 0)
            consumers = group.get("consumers", 0)
            if consumers > 0:
                lag_info[group_name] = pending // consumers
            else:
                lag_info[group_name] = pending

        return lag_info

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all consumers."""
        stats = {}
        for name, data in self._stats.items():
            stats[name] = {
                "messages_processed": data.messages_processed,
                "messages_acked": data.messages_acked,
                "messages_nacked": data.messages_nacked,
                "last_processed_at": data.last_processed_at,
            }
        return stats

    async def health_check(self) -> dict[str, Any]:
        """Check health of Redis connection and streams."""
        try:
            if not self._redis:
                return {"healthy": False, "error": "Not connected"}

            await self._redis.ping()

            stream_health = {}
            for stream_type in StreamType:
                try:
                    config = self._streams[stream_type]
                    length = await self._redis.xlen(config.name)
                    stream_health[stream_type.value] = {
                        "healthy": True,
                        "length": length,
                    }
                except Exception as e:
                    stream_health[stream_type.value] = {"healthy": False, "error": str(e)}

            return {
                "healthy": True,
                "connection": "active",
                "streams": stream_health,
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    async def cleanup_streams(self) -> None:
        """Remove all streams and consumer groups (for testing/reset)."""
        if not self._redis:
            return

        for config in self._streams.values():
            try:
                await self._redis.delete(config.name)
                logger.info(f"Deleted stream {config.name}")
            except redis.RedisError:
                pass


@asynccontextmanager
async def redis_connection():
    """Context manager for Redis connection lifecycle."""
    manager = RedisStreamManager()
    try:
        await manager.connect()
        yield manager
    finally:
        await manager.disconnect()
