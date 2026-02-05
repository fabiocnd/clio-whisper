from clio_api_server.app.models.transcript import (
    SegmentStatus,
    TranscriptSegment,
    UnconsolidatedTranscript,
    ConsolidatedTranscript,
    Question,
)


class TestTranscriptSegment:
    def test_segment_creation(self):
        segment = TranscriptSegment(
            segment_id=1,
            start_time=0.0,
            end_time=3.5,
            text="Hello, world",
        )
        assert segment.segment_id == 1
        assert segment.text == "Hello, world"
        assert segment.status == SegmentStatus.PARTIAL

    def test_normalized_text(self):
        segment = TranscriptSegment(
            segment_id=1,
            text="  Hello, world  ",
        )
        assert segment.normalized_text() == "Hello, world"

    def test_with_updated_text(self):
        segment = TranscriptSegment(
            segment_id=1,
            start_time=0.0,
            end_time=3.5,
            text="Hello",
            status=SegmentStatus.PARTIAL,
            revision=0,
        )
        updated = segment.with_updated_text("Hello, world")
        assert updated.text == "Hello, world"
        assert updated.revision == 1
        assert updated.start_time == 0.0


class TestUnconsolidatedTranscript:
    def test_add_segment(self):
        transcript = UnconsolidatedTranscript()
        segment = TranscriptSegment(
            segment_id=1,
            text="Test segment",
        )
        transcript.add_segment(segment)
        assert len(transcript.segments) == 1
        assert transcript.total_segments == 1

    def test_update_segment(self):
        transcript = UnconsolidatedTranscript()
        segment1 = TranscriptSegment(
            segment_id=1,
            text="Initial",
            revision=0,
        )
        transcript.add_segment(segment1)

        segment2 = TranscriptSegment(
            segment_id=1,
            text="Updated",
            revision=1,
        )
        result = transcript.update_segment(segment2)
        assert result is True
        assert transcript.segments[0].text == "Updated"

    def test_get_english_segments(self):
        transcript = UnconsolidatedTranscript()
        transcript.add_segment(TranscriptSegment(
            segment_id=1,
            text="Hello",
            is_english=True,
        ))
        transcript.add_segment(TranscriptSegment(
            segment_id=2,
            text="Bonjour",
            is_english=False,
        ))
        english = transcript.get_english_segments()
        assert len(english) == 1
        assert english[0].segment_id == 1


class TestConsolidatedTranscript:
    def test_update_from_segments(self):
        transcript = ConsolidatedTranscript()
        segments = [
            TranscriptSegment(
                segment_id=1,
                start_time=0.0,
                end_time=3.0,
                text="Hello",
                status=SegmentStatus.FINAL,
            ),
            TranscriptSegment(
                segment_id=2,
                start_time=3.0,
                end_time=6.0,
                text="World",
                status=SegmentStatus.FINAL,
            ),
        ]
        transcript.update_from_segments(segments)
        assert transcript.text == "Hello World"
        assert transcript.segment_count == 2
        assert transcript.revision == 1


class TestQuestion:
    def test_explicit_question_detection(self):
        segment = TranscriptSegment(
            segment_id=1,
            text="What is your name?",
        )
        question = Question.from_segment(segment)
        assert question is not None
        assert question.is_explicit is True

    def test_imperative_prompt_detection(self):
        segment = TranscriptSegment(
            segment_id=1,
            text="Imagine a world without war",
        )
        question = Question.from_segment(segment)
        assert question is not None
        assert "imperative" in question.source_types

    def test_non_english_filtered(self):
        segment = TranscriptSegment(
            segment_id=1,
            text="Comment allez-vous?",
            is_english=False,
        )
        question = Question.from_segment(segment)
        assert question is None
