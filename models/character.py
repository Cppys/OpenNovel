"""Character and world-building data models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from models.enums import CharacterRole, CharacterStatus, EventType, EventImportance


@dataclass
class Character:
    """Represents a character card."""
    id: Optional[int] = None
    novel_id: int = 0
    name: str = ""
    aliases: Optional[str] = None  # JSON array
    role: CharacterRole = CharacterRole.SUPPORTING
    description: str = ""
    background: str = ""
    abilities: Optional[str] = None  # JSON
    relationships: Optional[str] = None  # JSON: {character_name: relationship}
    first_appearance: Optional[int] = None  # Chapter number
    status: CharacterStatus = CharacterStatus.ACTIVE
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class WorldSetting:
    """Represents a world-building element."""
    id: Optional[int] = None
    novel_id: int = 0
    category: str = ""  # geography, power_system, faction, culture, rules
    name: str = ""
    description: str = ""
    parent_id: Optional[int] = None
    created_at: Optional[datetime] = None


@dataclass
class PlotEvent:
    """Represents a plot event or thread."""
    id: Optional[int] = None
    novel_id: int = 0
    chapter_number: Optional[int] = None
    event_type: EventType = EventType.SETUP
    description: str = ""
    resolved: bool = False
    resolution_chapter: Optional[int] = None
    importance: EventImportance = EventImportance.NORMAL
    created_at: Optional[datetime] = None
