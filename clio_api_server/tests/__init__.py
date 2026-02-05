import pytest


@pytest.fixture
def sample_segment():
    from clio_api_server.app.models.transcript import TranscriptSegment, SegmentStatus

    return TranscriptSegment(
        segment_id="1",
        start_time=0.0,
        end_time=3.5,
        text="Hello, how are you?",
        status=SegmentStatus.PARTIAL,
    )


@pytest.fixture
def sample_final_segment():
    from clio_api_server.app.models.transcript import TranscriptSegment, SegmentStatus

    return TranscriptSegment(
        segment_id="2",
        start_time=3.5,
        end_time=7.2,
        text="I'm doing well, thank you.",
        status=SegmentStatus.FINAL,
    )


@pytest.fixture
def sample_event():
    from clio_api_server.app.models.events import StreamingEvent, EventType

    return StreamingEvent(
        event_id="test_1",
        event_type=EventType.PARTIAL,
        segment_id="1",
        text="Hello, world",
    )
