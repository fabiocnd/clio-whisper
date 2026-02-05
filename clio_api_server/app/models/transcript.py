from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SegmentStatus(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    COMMITTED = "committed"


class TranscriptSegment(BaseModel):
    segment_id: int
    start_time: float = 0.0
    end_time: float = 0.0
    text: str = ""
    status: SegmentStatus = SegmentStatus.PARTIAL
    confidence: Optional[float] = None
    revision: int = 0
    source_client_uid: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    language: Optional[str] = None
    is_english: bool = True

    def normalized_text(self) -> str:
        return self.text.strip()

    def with_updated_text(self, text: str, status: Optional[SegmentStatus] = None) -> "TranscriptSegment":
        return TranscriptSegment(
            segment_id=self.segment_id,
            start_time=self.start_time,
            end_time=self.end_time,
            text=text,
            status=status or self.status,
            confidence=self.confidence,
            revision=self.revision + 1,
            source_client_uid=self.source_client_uid,
            created_at=self.created_at,
            updated_at=datetime.utcnow(),
            language=self.language,
            is_english=self.is_english,
        )


class UnconsolidatedTranscript(BaseModel):
    segments: List[TranscriptSegment] = Field(default_factory=list)
    total_segments: int = 0
    last_update: datetime = Field(default_factory=datetime.utcnow)

    def add_segment(self, segment: TranscriptSegment) -> None:
        existing = self._find_segment(segment.segment_id)
        if existing:
            if segment.revision > existing.revision:
                idx = self.segments.index(existing)
                self.segments[idx] = segment
        else:
            self.segments.append(segment)
        self.total_segments += 1
        self.last_update = datetime.utcnow()

    def update_segment(self, segment: TranscriptSegment) -> bool:
        existing = self._find_segment(segment.segment_id)
        if existing and segment.revision > existing.revision:
            idx = self.segments.index(existing)
            self.segments[idx] = segment
            self.last_update = datetime.utcnow()
            return True
        return False

    def commit_segment(self, segment_id: int) -> bool:
        for seg in self.segments:
            if seg.segment_id == segment_id and seg.status == SegmentStatus.FINAL:
                seg.status = SegmentStatus.COMMITTED
                seg.updated_at = datetime.utcnow()
                self.last_update = datetime.utcnow()
                return True
        return False

    def _find_segment(self, segment_id: int) -> Optional[TranscriptSegment]:
        for seg in self.segments:
            if seg.segment_id == segment_id:
                return seg
        return None

    def get_english_segments(self) -> List[TranscriptSegment]:
        return [s for s in self.segments if s.is_english]

    def get_final_segments(self) -> List[TranscriptSegment]:
        return [s for s in self.segments if s.status in (SegmentStatus.FINAL, SegmentStatus.COMMITTED)]


class ConsolidatedTranscript(BaseModel):
    text: str = ""
    revision: int = 0
    last_update: datetime = Field(default_factory=datetime.utcnow)
    segment_count: int = 0

    def update_from_segments(self, segments: List[TranscriptSegment]) -> None:
        finalized = [s for s in segments if s.status in (SegmentStatus.FINAL, SegmentStatus.COMMITTED)]
        new_text_parts = []
        for seg in sorted(finalized, key=lambda x: x.start_time):
            normalized = seg.normalized_text()
            if normalized:
                new_text_parts.append(normalized)
        new_text = " ".join(new_text_parts)
        if new_text != self.text:
            self.text = new_text
            self.revision += 1
            self.segment_count = len(finalized)
            self.last_update = datetime.utcnow()


class Question(BaseModel):
    question_id: str
    text: str
    normalized_text: str
    segment_ids: List[int] = Field(default_factory=list)
    first_seen: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    source_types: List[str] = Field(default_factory=list)
    is_explicit: bool = False

    @classmethod
    def from_segment(cls, segment: TranscriptSegment) -> Optional["Question"]:
        if not segment.is_english:
            return None
        text = segment.normalized_text()
        question_type = cls._detect_question_type(text)
        if question_type:
            return cls(
                question_id=cls._generate_id(text),
                text=text,
                normalized_text=text.lower().strip(),
                segment_ids=[segment.segment_id],
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                source_types=[question_type],
                is_explicit="?" in text or question_type in ["interrogative"],
            )
        return None

    @staticmethod
    def _detect_question_type(text: str) -> Optional[str]:
        text_lower = text.lower().strip()
        explicit_markers = ["?", "what", "how", "why", "when", "where", "who", "which", "whose"]
        implicit_markers = [
            "imagine", "describe", "show me", "tell me", "present", "explain",
            "what if", "let's say", "suppose", "consider"
        ]
        for marker in explicit_markers:
            if marker in text_lower:
                return "interrogative" if marker == "?" else "interrogative"
        for marker in implicit_markers:
            if text_lower.startswith(marker):
                return "imperative"
        return None

    @staticmethod
    def _generate_id(text: str) -> str:
        import hashlib
        normalized = text.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]
