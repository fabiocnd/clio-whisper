import asyncio
import json
import pytest
import redis.asyncio as aioredis
from datetime import datetime


@pytest.fixture
async def redis_client():
    client = aioredis.Redis(
        host="localhost",
        port=6379,
        db=0,
        password=None,
        decode_responses=True,
    )
    yield client
    await client.aclose()


@pytest.fixture
async def stream_manager():
    from clio_api_server.app.services.redis_stream_manager import RedisStreamManager

    manager = RedisStreamManager()
    await manager.connect()
    yield manager
    await manager.disconnect()


@pytest.mark.asyncio
async def test_redis_connection(stream_manager):
    health = await stream_manager.health_check()
    assert health["healthy"] is True
    assert health["connection"] == "active"


@pytest.mark.asyncio
async def test_audio_stream_exists(stream_manager):
    from clio_api_server.app.services.redis_stream_manager import StreamType

    audio_stream = stream_manager._streams[StreamType.AUDIO]
    assert audio_stream.name == "clio:audio"
    assert "clio:audio" in [s.name for s in stream_manager._streams.values()]


@pytest.mark.asyncio
async def test_segment_stream_exists(stream_manager):
    from clio_api_server.app.services.redis_stream_manager import StreamType

    segment_stream = stream_manager._streams[StreamType.SEGMENTS]
    assert segment_stream.name == "clio:segments"
    assert "clio:segments" in [s.name for s in stream_manager._streams.values()]


@pytest.mark.asyncio
async def test_event_stream_exists(stream_manager):
    from clio_api_server.app.services.redis_stream_manager import StreamType

    event_stream = stream_manager._streams[StreamType.EVENTS]
    assert event_stream.name == "clio:events"
    assert "clio:events" in [s.name for s in stream_manager._streams.values()]


@pytest.mark.asyncio
async def test_publish_and_read_audio(stream_manager, redis_client):
    test_audio = b"test audio data"
    metadata = {"device_index": -1, "sample_rate": 16000, "chunk_id": "test-123"}

    msg_id = await stream_manager.publish_audio(test_audio, metadata)
    assert msg_id is not None

    messages = await redis_client.xrange("clio:audio", count=100)
    assert len(messages) >= 1

    found = False
    for msg in messages:
        if "test-123" in str(msg):
            found = True
            break
    assert found is True

    await redis_client.delete("clio:audio")


@pytest.mark.asyncio
async def test_publish_and_read_segment(stream_manager, redis_client):
    test_segment = {
        "segment_id": "seg-456",
        "text": "Hello world",
        "start_time": 0.0,
        "end_time": 2.5,
        "confidence": 0.95,
    }

    msg_id = await stream_manager.publish_segment(test_segment)
    assert msg_id is not None

    messages = await redis_client.xrange("clio:segments", count=100)
    assert len(messages) >= 1

    await redis_client.delete("clio:segments")


@pytest.mark.asyncio
async def test_publish_and_read_event(stream_manager, redis_client):
    test_event = {
        "event_type": "segment",
        "data": json.dumps({"segment_id": "seg-789", "text": "Test event"}),
    }

    msg_id = await stream_manager.publish_event(test_event)
    assert msg_id is not None

    messages = await redis_client.xrange("clio:events", count=100)
    assert len(messages) >= 1

    await redis_client.delete("clio:events")


@pytest.mark.asyncio
async def test_get_stream_info(stream_manager):
    from clio_api_server.app.services.redis_stream_manager import StreamType

    info = await stream_manager.get_stream_info(StreamType.AUDIO)
    assert "stream" in info
    assert "length" in info
    assert "consumer_groups" in info


@pytest.mark.asyncio
async def test_consumer_lag(stream_manager):
    from clio_api_server.app.services.redis_stream_manager import StreamType

    lag = await stream_manager.get_consumer_lag(StreamType.AUDIO)
    assert isinstance(lag, dict)


@pytest.mark.asyncio
async def test_register_handler(stream_manager):
    from clio_api_server.app.services.redis_stream_manager import StreamType

    async def dummy_handler(msg_id, data):
        pass

    stream_manager.register_handler(StreamType.AUDIO, dummy_handler)
    assert StreamType.AUDIO in stream_manager._message_handlers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
