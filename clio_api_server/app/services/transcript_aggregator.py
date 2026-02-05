import asyncio
import hashlib
from datetime import datetime
from typing import Callable, Dict, List, Optional

from loguru import logger

from clio_api_server.app.core.config import AggregationConfig, EnglishConfig, get_settings
from clio_api_server.app.models.events import EventType, StreamingEvent
from clio_api_server.app.models.transcript import (
    SegmentStatus,
    TranscriptSegment,
    UnconsolidatedTranscript,
    ConsolidatedTranscript,
    Question,
)


class TranscriptAggregator:
    def __init__(
        self,
        aggregation_config: Optional[AggregationConfig] = None,
        english_config: Optional[EnglishConfig] = None,
        event_callback: Optional[Callable[[StreamingEvent], None]] = None,
    ):
        self.aggregation_config = aggregation_config or get_settings().aggregation
        self.english_config = english_config or get_settings().english
        self.event_callback = event_callback

        self.unconsolidated = UnconsolidatedTranscript()
        self.consolidated = ConsolidatedTranscript()
        self.questions: Dict[str, Question] = {}
        self._commit_timestamps: Dict[int, datetime] = {}
        self._segment_text_cache: Dict[int, str] = {}

    def register_event_callback(self, callback: Callable[[StreamingEvent], None]) -> None:
        self.event_callback = callback

    def _is_english(self, language: Optional[str], confidence: Optional[float]) -> bool:
        if not self.english_config.enforce_english:
            return True
        if language is None:
            return True
        is_english = language.lower() in ("en", "english")
        if confidence is not None and not is_english:
            if confidence >= self.english_config.min_english_confidence:
                return False
        return True

    def _normalize_text(self, text: str) -> str:
        import re
        text = text.strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r" ([.,!?;:])", r"\1", text)
        return text

    def _should_commit_segment(self, segment_id: int, status: SegmentStatus) -> bool:
        if status != SegmentStatus.FINAL:
            return False
        now = datetime.utcnow()
        if segment_id in self._commit_timestamps:
            last_commit = self._commit_timestamps[segment_id]
            elapsed = (now - last_commit).total_seconds()
            if elapsed < self.aggregation_config.commit_delay_seconds:
                return False
        self._commit_timestamps[segment_id] = now
        return True

    def _handle_segment_event(self, event: StreamingEvent) -> None:
        segment_id = event.segment_id
        if segment_id is None:
            return

        text = event.text or ""
        normalized_text = self._normalize_text(text)
        is_final = event.event_type == EventType.FINAL

        existing = self._find_segment(segment_id)
        current_text = self._segment_text_cache.get(segment_id, "")

        if existing and normalized_text == current_text:
            if is_final and existing.status != SegmentStatus.COMMITTED:
                if self._should_commit_segment(segment_id, SegmentStatus.FINAL):
                    existing.status = SegmentStatus.COMMITTED
                    existing.updated_at = datetime.utcnow()
                    self._update_consolidated_transcript()
                    self._extract_questions(existing)
            return

        if existing:
            if normalized_text != current_text:
                self._segment_text_cache[segment_id] = normalized_text
                new_segment = existing.with_updated_text(
                    normalized_text,
                    SegmentStatus.FINAL if is_final else SegmentStatus.PARTIAL
                )
                self.unconsolidated.update_segment(new_segment)
        else:
            segment = TranscriptSegment(
                segment_id=segment_id,
                start_time=event.data.get("start", 0.0),
                end_time=event.data.get("end", 0.0),
                text=normalized_text,
                status=SegmentStatus.FINAL if is_final else SegmentStatus.PARTIAL,
                revision=1,
                source_client_uid=event.client_uid,
                language=event.data.get("language"),
                is_english=True,
            )
            self._segment_text_cache[segment_id] = normalized_text
            self.unconsolidated.add_segment(segment)

        self._enforce_limits()

        if is_final and self._should_commit_segment(segment_id, SegmentStatus.FINAL):
            self.unconsolidated.commit_segment(segment_id)
            self._update_consolidated_transcript()
            if segment := self._find_segment(segment_id):
                self._extract_questions(segment)

        self._emit_system_event("segment_updated", {"segment_id": segment_id})

    def _find_segment(self, segment_id: int) -> Optional[TranscriptSegment]:
        return self.unconsolidated._find_segment(segment_id)

    def _update_consolidated_transcript(self) -> None:
        self.consolidated.update_from_segments(self.unconsolidated.segments)

    def _extract_questions(self, segment: TranscriptSegment) -> None:
        question = Question.from_segment(segment)
        if not question:
            return

        question_id = question.question_id
        if question_id in self.questions:
            existing = self.questions[question_id]
            if segment.segment_id not in existing.segment_ids:
                existing.segment_ids.append(segment.segment_id)
            existing.last_seen = datetime.utcnow()
        else:
            self.questions[question_id] = question
            self._enforce_question_limits()

        if self.event_callback:
            self.event_callback(StreamingEvent(
                event_id=f"question_{question_id[:8]}",
                event_type=EventType.SYSTEM,
                data={"type": "question_extracted", "question": question.model_dump()},
            ))

    def _enforce_limits(self) -> None:
        max_segs = self.aggregation_config.max_unconsolidated_segments
        while len(self.unconsolidated.segments) > max_segs:
            oldest = min(self.unconsolidated.segments, key=lambda s: s.created_at)
            self.unconsolidated.segments.remove(oldest)
            self._segment_text_cache.pop(oldest.segment_id, None)
            self._commit_timestamps.pop(oldest.segment_id, None)

    def _enforce_question_limits(self) -> None:
        max_qs = self.aggregation_config.max_questions
        if len(self.questions) > max_qs:
            sorted_questions = sorted(
                self.questions.items(),
                key=lambda x: x[1].first_seen,
            )
            to_remove = len(self.questions) - max_qs
            for qid, _ in sorted_questions[:to_remove]:
                del self.questions[qid]

    def _emit_system_event(self, event_type: str, data: dict) -> None:
        if self.event_callback:
            self.event_callback(StreamingEvent(
                event_id=f"sys_{datetime.utcnow().timestamp()}",
                event_type=EventType.SYSTEM,
                data={"aggregator_event": event_type, **data},
            ))

    async def process_event(self, event: StreamingEvent) -> None:
        if event.event_type in (EventType.PARTIAL, EventType.FINAL):
            self._handle_segment_event(event)
        elif event.event_type == EventType.LANGUAGE_DETECTED:
            lang = event.data.get("language")
            prob = event.data.get("probability")
            if not self._is_english(lang, prob):
                logger.warning(f"Non-English detected: {lang} (confidence: {prob})")

    def get_unconsolidated(self) -> UnconsolidatedTranscript:
        return self.unconsolidated

    def get_consolidated(self) -> ConsolidatedTranscript:
        return self.consolidated

    def get_questions(self) -> List[Question]:
        return list(self.questions.values())

    def reset(self) -> None:
        self.unconsolidated = UnconsolidatedTranscript()
        self.consolidated = ConsolidatedTranscript()
        self.questions = {}
        self._commit_timestamps = {}
        self._segment_text_cache = {}
