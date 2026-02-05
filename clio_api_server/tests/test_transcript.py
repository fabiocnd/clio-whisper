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
            segment_id="1",
            start_time=0.0,
            end_time=3.5,
            text="Hello, world",
        )
        assert segment.segment_id == "1"
        assert segment.text == "Hello, world"
        assert segment.status == SegmentStatus.PARTIAL

    def test_normalized_text(self):
        segment = TranscriptSegment(
            segment_id="1",
            text="  Hello, world  ",
        )
        assert segment.normalized_text() == "Hello, world"

    def test_with_updated_text(self):
        segment = TranscriptSegment(
            segment_id="1",
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
            segment_id="1",
            text="Test segment",
        )
        transcript.add_segment(segment)
        assert len(transcript.segments) == 1
        assert transcript.total_segments == 1

    def test_update_segment(self):
        transcript = UnconsolidatedTranscript()
        segment1 = TranscriptSegment(
            segment_id="1",
            text="Initial",
            revision=0,
        )
        transcript.add_segment(segment1)

        segment2 = TranscriptSegment(
            segment_id="1",
            text="Updated",
            revision=1,
        )
        result = transcript.update_segment(segment2)
        assert result is True
        assert transcript.segments[0].text == "Updated"

    def test_get_english_segments(self):
        transcript = UnconsolidatedTranscript()
        transcript.add_segment(
            TranscriptSegment(
                segment_id="1",
                text="Hello",
                is_english=True,
            )
        )
        transcript.add_segment(
            TranscriptSegment(
                segment_id="2",
                text="Bonjour",
                is_english=False,
            )
        )
        english = transcript.get_english_segments()
        assert len(english) == 1
        assert english[0].segment_id == "1"


class TestConsolidatedTranscript:
    def test_update_from_segments(self):
        transcript = ConsolidatedTranscript()
        unconsolidated = UnconsolidatedTranscript()
        segments = [
            TranscriptSegment(
                segment_id="1",
                start_time=0.0,
                end_time=3.0,
                text="Hello",
                status=SegmentStatus.FINAL,
            ),
            TranscriptSegment(
                segment_id="2",
                start_time=3.0,
                end_time=6.0,
                text="World",
                status=SegmentStatus.FINAL,
            ),
        ]
        for seg in segments:
            unconsolidated.add_segment(seg)
            unconsolidated.commit_segment(seg.segment_id)
        transcript.update_from_segments(unconsolidated.get_committed_segments())
        assert transcript.text == "Hello World"
        assert transcript.segment_count == 2
        assert transcript.revision == 1

    def test_exact_match_deduplication(self):
        transcript = ConsolidatedTranscript()
        transcript.text = "Hello World"
        unconsolidated = UnconsolidatedTranscript()
        duplicate = TranscriptSegment(
            segment_id="dup1",
            start_time=0.0,
            end_time=3.0,
            text="Hello World",
            status=SegmentStatus.FINAL,
        )
        unconsolidated.add_segment(duplicate)
        unconsolidated.commit_segment("dup1")
        transcript.update_from_segments(unconsolidated.get_committed_segments())
        assert transcript.text == "Hello World"
        assert transcript.revision == 0

    def test_substring_match_deduplication(self):
        transcript = ConsolidatedTranscript()
        transcript.text = "Hello World how are you"
        unconsolidated = UnconsolidatedTranscript()
        substring = TranscriptSegment(
            segment_id="sub1",
            start_time=0.0,
            end_time=3.0,
            text="World how are you",
            status=SegmentStatus.FINAL,
        )
        unconsolidated.add_segment(substring)
        unconsolidated.commit_segment("sub1")
        transcript.update_from_segments(unconsolidated.get_committed_segments())
        assert transcript.text == "Hello World how are you"
        assert transcript.revision == 0

    def test_similarity_deduplication(self):
        transcript = ConsolidatedTranscript()
        transcript.text = "Hello there how are you doing today my friend"
        unconsolidated = UnconsolidatedTranscript()
        similar = TranscriptSegment(
            segment_id="sim1",
            start_time=0.0,
            end_time=3.0,
            text="Hello there how are you doing today",
            status=SegmentStatus.FINAL,
        )
        unconsolidated.add_segment(similar)
        unconsolidated.commit_segment("sim1")
        transcript.update_from_segments(unconsolidated.get_committed_segments())
        assert transcript.text == "Hello there how are you doing today my friend"
        assert transcript.revision == 0

    def test_hash_deduplication_prevents_replay(self):
        transcript = ConsolidatedTranscript()
        unconsolidated = UnconsolidatedTranscript()
        segment1 = TranscriptSegment(
            segment_id="hash1",
            start_time=0.0,
            end_time=3.0,
            text="Unique content here",
            status=SegmentStatus.FINAL,
        )
        unconsolidated.add_segment(segment1)
        unconsolidated.commit_segment("hash1")
        transcript.update_from_segments(unconsolidated.get_committed_segments())
        assert transcript.text == "Unique content here"
        unconsolidated2 = UnconsolidatedTranscript()
        segment2 = TranscriptSegment(
            segment_id="hash2",
            start_time=0.0,
            end_time=3.0,
            text="Unique content here",
            status=SegmentStatus.FINAL,
        )
        unconsolidated2.add_segment(segment2)
        unconsolidated2.commit_segment("hash2")
        transcript.update_from_segments(unconsolidated2.get_committed_segments())
        assert transcript.text == "Unique content here"
        assert transcript.revision == 1

    def test_reset_clears_state(self):
        transcript = ConsolidatedTranscript()
        transcript.text = "Some content"
        transcript.segment_count = 5
        transcript.revision = 3
        transcript.reset()
        assert transcript.text == ""
        assert transcript.segment_count == 0
        assert transcript.revision == 0
        assert transcript._committed_hashes == {}


class TestQuestion:
    def test_explicit_question_detection(self):
        segment = TranscriptSegment(
            segment_id="1",
            text="What is your name?",
        )
        question = Question.from_segment(segment)
        assert question is not None
        assert question.is_explicit is True

    def test_imperative_prompt_detection(self):
        segment = TranscriptSegment(
            segment_id="1",
            text="Imagine a world without war",
        )
        question = Question.from_segment(segment)
        assert question is not None
        assert "imperative" in question.source_types

    def test_non_english_filtered(self):
        segment = TranscriptSegment(
            segment_id="1",
            text="Comment allez-vous?",
            is_english=False,
        )
        question = Question.from_segment(segment)
        assert question is None
