import hashlib
import re
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class SegmentStatus(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"
    COMMITTED = "committed"


class TranscriptSegment(BaseModel):
    segment_id: str
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
    text_hash: Optional[str] = None

    def normalized_text(self) -> str:
        text = self.text.strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r" ([.,!?;:])", r"\1", text)
        return text

    def compute_hash(self) -> str:
        normalized = self.normalized_text().lower()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def with_updated_text(
        self, text: str, status: Optional[SegmentStatus] = None
    ) -> "TranscriptSegment":
        self.text = text
        self.text_hash = self.compute_hash()
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
            text_hash=self.text_hash,
        )


class CommitLedger(BaseModel):
    committed_hashes: dict[str, datetime] = Field(default_factory=dict)
    last_commit_time: Optional[datetime] = None


class UnconsolidatedTranscript(BaseModel):
    segments: List[TranscriptSegment] = Field(default_factory=list)
    total_segments: int = 0
    last_update: datetime = Field(default_factory=datetime.utcnow)

    def add_segment(self, segment: TranscriptSegment) -> None:
        if segment.text_hash is None:
            segment.text_hash = segment.compute_hash()

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
        if segment.text_hash is None:
            segment.text_hash = segment.compute_hash()

        existing = self._find_segment(segment.segment_id)
        if existing and segment.revision > existing.revision:
            idx = self.segments.index(existing)
            self.segments[idx] = segment
            self.last_update = datetime.utcnow()
            return True
        return False

    def commit_segment(self, segment_id: str) -> bool:
        for seg in self.segments:
            if seg.segment_id == segment_id and seg.status == SegmentStatus.FINAL:
                seg.status = SegmentStatus.COMMITTED
                seg.updated_at = datetime.utcnow()
                if seg.text_hash is None:
                    seg.text_hash = seg.compute_hash()
                self.last_update = datetime.utcnow()
                return True
        return False

    def _find_segment(self, segment_id: str) -> Optional[TranscriptSegment]:
        for seg in self.segments:
            if seg.segment_id == segment_id:
                return seg
        return None

    def get_english_segments(self) -> List[TranscriptSegment]:
        return [s for s in self.segments if s.is_english]

    def get_final_segments(self) -> List[TranscriptSegment]:
        return [
            s for s in self.segments if s.status in (SegmentStatus.FINAL, SegmentStatus.COMMITTED)
        ]

    def get_committed_segments(self) -> List[TranscriptSegment]:
        return [s for s in self.segments if s.status == SegmentStatus.COMMITTED]


class ConsolidatedTranscript(BaseModel):
    text: str = ""
    revision: int = 0
    last_update: datetime = Field(default_factory=datetime.utcnow)
    segment_count: int = 0

    def __init__(self, **data):
        super().__init__(**data)
        self._committed_hashes = {}

    def update_from_segments(
        self,
        segments: List[TranscriptSegment],
        commit_ledger: Optional[CommitLedger] = None,
    ) -> None:
        committed = [s for s in segments if s.status == SegmentStatus.COMMITTED]

        if not committed:
            return

        new_segments = []
        for seg in sorted(committed, key=lambda x: (x.start_time, x.segment_id)):
            normalized = seg.normalized_text()
            if not normalized:
                continue

            if seg.text_hash and seg.text_hash in self._committed_hashes:
                continue

            current_lower = self.text.lower().strip() if self.text else ""
            normalized_lower = normalized.lower().strip()

            current_words = set(current_lower.split())
            new_words = set(normalized_lower.split())

            is_exact_match = current_lower == normalized_lower
            is_substring_match = normalized_lower and normalized_lower in current_lower
            is_highly_similar = (
                len(new_words) > 0 and len(current_words & new_words) / len(new_words) > 0.8
            )

            if is_exact_match or is_substring_match or is_highly_similar:
                if seg.text_hash:
                    self._committed_hashes[seg.text_hash] = datetime.utcnow()
                continue

            new_segments.append(seg)
            if seg.text_hash:
                self._committed_hashes[seg.text_hash] = datetime.utcnow()

        if not new_segments:
            return

        for seg in new_segments:
            normalized = seg.normalized_text()
            if not normalized:
                continue

            suffix = self._get_non_overlapping_suffix(normalized, self.text)
            if suffix:
                if self.text and not self.text.endswith(" "):
                    self.text += " "
                self.text += suffix

        self.text = self.text.strip()
        self.revision += 1
        self.segment_count = len(committed)
        self.last_update = datetime.utcnow()

    def _get_non_overlapping_suffix(self, new_text: str, current_text: str) -> str:
        if not current_text:
            return new_text.strip()

        current_normalized = current_text.lower().strip()
        new_normalized = new_text.lower().strip()

        if new_normalized.startswith(current_normalized):
            return ""

        if current_normalized.endswith(new_normalized):
            return ""

        words_current = current_normalized.split()
        words_new = new_normalized.split()

        max_overlap = 0
        for i in range(len(words_new), 0, -1):
            suffix_new = " ".join(words_new[-i:])
            suffix_current = " ".join(words_current[-i:]) if len(words_current) >= i else ""
            if suffix_new == suffix_current:
                max_overlap = i
                break

        if max_overlap > 0:
            return " ".join(words_new[max_overlap:]).strip()

        return new_text.strip()

    def reset(self) -> None:
        self.text = ""
        self.revision = 0
        self.segment_count = 0
        self.last_update = datetime.utcnow()
        self._committed_hashes = {}


class Question(BaseModel):
    question_id: str
    text: str
    normalized_text: str
    segment_ids: List[str] = Field(default_factory=list)
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
            "imagine",
            "describe",
            "show me",
            "tell me",
            "present",
            "explain",
            "what if",
            "let's say",
            "suppose",
            "consider",
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
