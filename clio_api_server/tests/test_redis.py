import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


class TestRedisStreamManager:
    """Tests for RedisStreamManager."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.ping = AsyncMock(return_value=True)
        redis.xadd = AsyncMock(return_value="1234567890-0")
        redis.xlen = AsyncMock(return_value=10)
        redis.xinfo_stream = AsyncMock(return_value={"length": 10})
        redis.xinfo_groups = AsyncMock(return_value=[])
        redis.xgroup_create = AsyncMock()
        redis.xreadgroup = AsyncMock(return_value=[])
        redis.xack = AsyncMock(return_value=1)
        redis.close = AsyncMock()
        return redis

    @pytest.fixture
    def stream_manager(self, mock_redis):
        """Create a stream manager with mocked Redis."""
        with patch("redis.asyncio.Redis", return_value=mock_redis):
            from clio_api_server.app.services.redis_stream_manager import RedisStreamManager

            manager = RedisStreamManager()
            manager._redis = mock_redis
            return manager

    def test_streams_configured(self, stream_manager):
        """Test that streams are properly configured."""
        from clio_api_server.app.services.redis_stream_manager import StreamType

        assert len(stream_manager._streams) == 3
        assert StreamType.AUDIO in stream_manager._streams
        assert StreamType.SEGMENTS in stream_manager._streams
        assert StreamType.EVENTS in stream_manager._streams

    def test_stream_names_have_prefix(self, stream_manager):
        """Test that stream names use the configured prefix."""
        prefix = stream_manager.settings.redis_stream_prefix

        for stream_type, config in stream_manager._streams.items():
            assert config.name.startswith(prefix)
            assert config.consumer_group.startswith(prefix)

    @pytest.mark.asyncio
    async def test_connect_success(self, stream_manager):
        """Test successful Redis connection (expected to fail without Redis)."""
        from clio_api_server.app.services.redis_stream_manager import RedisConnectionError

        with pytest.raises(RedisConnectionError):
            await stream_manager.connect()

    @pytest.mark.asyncio
    async def test_publish_audio(self, stream_manager, mock_redis):
        """Test publishing audio to stream."""
        audio_chunk = b"test audio data"
        metadata = {"device_index": -1, "sample_rate": 16000}

        msg_id = await stream_manager.publish_audio(audio_chunk, metadata)

        assert msg_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_segment(self, stream_manager, mock_redis):
        """Test publishing segment to stream."""
        segment_data = {
            "segment_id": "seg_001",
            "text": "Hello world",
            "start_time": 0.0,
            "end_time": 3.5,
        }

        msg_id = await stream_manager.publish_segment(segment_data)

        assert msg_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_event(self, stream_manager, mock_redis):
        """Test publishing event to stream."""
        event_data = {
            "event_type": "segment_updated",
            "segment_id": "seg_001",
        }

        msg_id = await stream_manager.publish_event(event_data)

        assert msg_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_handler(self, stream_manager):
        """Test registering a message handler."""
        from clio_api_server.app.services.redis_stream_manager import StreamType

        async def dummy_handler(msg_id, data):
            pass

        stream_manager.register_handler(StreamType.AUDIO, dummy_handler)

        assert StreamType.AUDIO in stream_manager._message_handlers
        assert stream_manager._message_handlers[StreamType.AUDIO] == dummy_handler

    @pytest.mark.asyncio
    async def test_get_stream_info(self, stream_manager, mock_redis):
        """Test getting stream information."""
        from clio_api_server.app.services.redis_stream_manager import StreamType

        info = await stream_manager.get_stream_info(StreamType.AUDIO)

        assert "stream" in info
        assert "length" in info
        assert "consumer_groups" in info

    @pytest.mark.asyncio
    async def test_health_check(self, stream_manager, mock_redis):
        """Test health check."""
        health = await stream_manager.health_check()

        assert health["healthy"] is True
        assert "streams" in health


class TestWorkerPool:
    """Tests for WorkerPool."""

    @pytest.fixture
    def mock_stream_manager(self):
        """Create a mock stream manager."""
        manager = MagicMock()
        manager.register_handler = MagicMock()
        return manager

    @pytest.fixture
    def worker_pool(self, mock_stream_manager):
        """Create a worker pool with mocked manager."""
        from clio_api_server.app.services.redis_workers import WorkerPool

        pool = WorkerPool(mock_stream_manager)
        return pool

    def test_create_transcription_workers(self, worker_pool, mock_stream_manager):
        """Test creating transcription workers."""
        worker_pool.create_transcription_workers(count=2)

        assert len(worker_pool.transcription_workers) == 2
        assert mock_stream_manager.register_handler.call_count == 2

    def test_create_aggregation_workers(self, worker_pool, mock_stream_manager):
        """Test creating aggregation workers."""
        worker_pool.create_aggregation_workers(count=2)

        assert len(worker_pool.aggregation_workers) == 2
        assert mock_stream_manager.register_handler.call_count == 2

    def test_create_broadcast_workers(self, worker_pool, mock_stream_manager):
        """Test creating broadcast workers."""
        worker_pool.create_broadcast_workers(count=1)

        assert len(worker_pool.broadcast_workers) == 1

    def test_get_aggregator(self, worker_pool):
        """Test getting aggregator worker."""
        worker_pool.create_aggregation_workers(count=1)

        aggregator = worker_pool.get_aggregator()

        assert aggregator is not None

    def test_get_broadcaster(self, worker_pool):
        """Test getting broadcast worker."""
        worker_pool.create_broadcast_workers(count=1)

        broadcaster = worker_pool.get_broadcaster()

        assert broadcaster is not None


class TestAggregationWorker:
    """Tests for AggregationWorker."""

    @pytest.fixture
    def mock_stream_manager(self):
        """Create a mock stream manager."""
        manager = MagicMock()
        manager.publish_event = AsyncMock()
        return manager

    @pytest.fixture
    def worker(self, mock_stream_manager):
        """Create an aggregation worker."""
        from clio_api_server.app.services.redis_workers import AggregationWorker

        return AggregationWorker(mock_stream_manager)

    def test_normalize_text(self, worker):
        """Test text normalization."""
        assert worker._normalize_text("  Hello   world  ") == "Hello world"

    def test_is_english_question(self, worker):
        """Test English question detection."""
        assert worker._is_english_question("What is your name?") is True
        assert worker._is_english_question("How are you doing?") is True
        assert worker._is_english_question("This is a statement") is False

    def test_generate_question_id(self, worker):
        """Test question ID generation."""
        id1 = worker._generate_question_id("What is your name?")
        id2 = worker._generate_question_id("What is your name?")

        assert id1 == id2
        assert len(id1) == 16

    @pytest.mark.asyncio
    async def test_process_message_new_segment(self, worker, mock_stream_manager):
        """Test processing a new segment message."""
        msg_id = "1234567890-0"
        data = {
            "data": '{"segment_id": "seg_001", "text": "Hello world", "start_time": 0.0, "end_time": 3.5, "confidence": 0.95, "language": "en", "completed": true}',
            "correlation_id": "abc123",
        }

        await worker.process_message(msg_id, data)

        assert len(worker.unconsolidated.segments) == 1
        assert worker.unconsolidated.segments[0].text == "Hello world"

    @pytest.mark.asyncio
    async def test_process_message_question_extraction(self, worker, mock_stream_manager):
        """Test question extraction from segment."""
        msg_id = "1234567890-0"
        data = {
            "data": '{"segment_id": "seg_001", "text": "What is your name?", "start_time": 0.0, "end_time": 3.5, "confidence": 0.95, "language": "en", "completed": true}',
            "correlation_id": "abc123",
        }

        await worker.process_message(msg_id, data)

        assert len(worker.questions) == 1
        question = list(worker.questions.values())[0]
        assert question.is_explicit is True

    def test_get_unconsolidated(self, worker):
        """Test getting unconsolidated transcript."""
        unconsolidated = worker.get_unconsolidated()

        assert unconsolidated is not None
        assert hasattr(unconsolidated, "segments")

    def test_get_consolidated(self, worker):
        """Test getting consolidated transcript."""
        consolidated = worker.get_consolidated()

        assert consolidated is not None
        assert hasattr(consolidated, "text")

    def test_get_questions(self, worker):
        """Test getting questions."""
        questions = worker.get_questions()

        assert isinstance(questions, list)


class TestBroadcastWorker:
    """Tests for BroadcastWorker."""

    @pytest.fixture
    def mock_stream_manager(self):
        """Create a mock stream manager."""
        manager = MagicMock()
        return manager

    @pytest.fixture
    def worker(self, mock_stream_manager):
        """Create a broadcast worker."""
        from clio_api_server.app.services.redis_workers import BroadcastWorker

        return BroadcastWorker(mock_stream_manager)

    def test_add_sse_client(self, worker):
        """Test adding SSE client."""
        queue = asyncio.Queue()

        worker.add_sse_client(queue)

        assert queue in worker._sse_queues

    def test_remove_sse_client(self, worker):
        """Test removing SSE client."""
        queue = asyncio.Queue()
        worker._sse_queues.append(queue)

        worker.remove_sse_client(queue)

        assert queue not in worker._sse_queues

    def test_add_ws_client(self, worker):
        """Test adding WebSocket client."""
        queue = asyncio.Queue()

        worker.add_ws_client(queue)

        assert queue in worker._ws_queues

    def test_remove_ws_client(self, worker):
        """Test removing WebSocket client."""
        queue = asyncio.Queue()
        worker._ws_queues.append(queue)

        worker.remove_ws_client(queue)

        assert queue not in worker._ws_queues


class TestRedisPipeline:
    """Tests for RedisPipeline."""

    @pytest.fixture
    def pipeline(self):
        """Create a Redis pipeline."""
        with patch("redis.asyncio.Redis"):
            from clio_api_server.app.services.redis_pipeline import RedisPipeline

            return RedisPipeline()

    def test_initial_state(self, pipeline):
        """Test initial pipeline state."""
        from clio_api_server.app.models.control import PipelineState

        assert pipeline.state == PipelineState.STOPPED
        assert pipeline._running is False
        assert pipeline.stream_manager is None
        assert pipeline.worker_pool is None

    def test_add_sse_client(self, pipeline):
        """Test adding SSE client."""
        queue = pipeline.add_sse_client()

        assert queue is not None
        assert queue in pipeline._sse_clients

    def test_remove_sse_client(self, pipeline):
        """Test removing SSE client."""
        queue = pipeline.add_sse_client()

        pipeline.remove_sse_client(queue)

        assert queue not in pipeline._sse_clients

    def test_add_ws_client(self, pipeline):
        """Test adding WebSocket client."""
        queue = pipeline.add_ws_client()

        assert queue is not None
        assert queue in pipeline._ws_clients

    def test_remove_ws_client(self, pipeline):
        """Test removing WebSocket client."""
        queue = pipeline.add_ws_client()

        pipeline.remove_ws_client(queue)

        assert queue not in pipeline._ws_clients

    def test_reset(self, pipeline):
        """Test pipeline reset."""
        from clio_api_server.app.models.control import PipelineState

        pipeline.state = PipelineState.RUNNING
        pipeline._sse_clients.append(asyncio.Queue())

        pipeline.reset()

        assert pipeline.state == PipelineState.STOPPED
        assert len(pipeline._sse_clients) == 0
        assert len(pipeline._ws_clients) == 0
