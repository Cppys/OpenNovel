"""Chapter data model."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from models.enums import ChapterStatus


@dataclass
class Chapter:
    """Represents a single chapter."""
    id: Optional[int] = None
    novel_id: int = 0
    volume_id: Optional[int] = None
    chapter_number: int = 0
    title: str = ""
    content: Optional[str] = None
    char_count: int = 0
    outline: Optional[str] = None
    hook: Optional[str] = None
    status: ChapterStatus = ChapterStatus.PLANNED
    review_score: Optional[float] = None
    review_notes: Optional[str] = None
    revision_count: int = 0
    fanqie_chapter_id: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Outline:
    """Represents a chapter outline entry."""
    id: Optional[int] = None
    novel_id: int = 0
    volume_id: Optional[int] = None
    chapter_number: int = 0
    outline_text: str = ""
    key_scenes: Optional[str] = None  # JSON array
    characters_involved: Optional[str] = None  # JSON array
    emotional_tone: str = ""
    hook_type: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
