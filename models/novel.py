"""Novel data model."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from models.enums import NovelStatus


@dataclass
class Novel:
    """Represents a novel and its metadata."""
    id: Optional[int] = None
    title: str = ""
    genre: str = ""
    synopsis: str = ""
    style_guide: str = ""
    target_chapter_count: int = 0  # 0 = ongoing
    chapters_per_volume: int = 30
    planning_metadata: Optional[str] = None  # JSON: genre_brief, plot_backbone, volumes meta
    status: NovelStatus = NovelStatus.PLANNING
    fanqie_book_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class Volume:
    """Represents a volume/arc within a novel."""
    id: Optional[int] = None
    novel_id: int = 0
    volume_number: int = 1
    title: str = ""
    synopsis: str = ""
    target_chapters: int = 30
    created_at: Optional[datetime] = None
