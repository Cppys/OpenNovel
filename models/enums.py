"""Enumerations for novel workflow status tracking."""

from enum import Enum


class NovelStatus(str, Enum):
    PLANNING = "planning"
    WRITING = "writing"
    PAUSED = "paused"
    COMPLETED = "completed"


class ChapterStatus(str, Enum):
    PLANNED = "planned"
    DRAFTED = "drafted"
    EDITED = "edited"
    REVIEWED = "reviewed"
    PUBLISHED = "published"


class CharacterRole(str, Enum):
    PROTAGONIST = "protagonist"
    ANTAGONIST = "antagonist"
    SUPPORTING = "supporting"
    MINOR = "minor"


class CharacterStatus(str, Enum):
    ACTIVE = "active"
    DECEASED = "deceased"
    ABSENT = "absent"


class EventType(str, Enum):
    FORESHADOW = "foreshadow"
    CLIMAX = "climax"
    REVEAL = "reveal"
    TWIST = "twist"
    SETUP = "setup"
    RESOLUTION = "resolution"


class EventImportance(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    NORMAL = "normal"
    MINOR = "minor"


class PublishMode(str, Enum):
    PUBLISH = "publish"
    DRAFT = "draft"
    PRE_PUBLISH = "pre-publish"


class HookType(str, Enum):
    CLIFFHANGER = "cliffhanger"
    REVELATION = "revelation"
    QUESTION = "question"
    TWIST = "twist"
    PROMISE = "promise"


class EmotionalTone(str, Enum):
    TENSE = "紧张"
    WARM = "温馨"
    SAD = "悲伤"
    HOT_BLOODED = "热血"
    FUNNY = "搞笑"
    SUSPENSE = "悬疑"
    ROMANTIC = "浪漫"
    DARK = "黑暗"
    CALM = "平静"
