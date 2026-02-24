"""SQLite database initialization and CRUD operations."""

import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from models.novel import Novel, Volume
from models.chapter import Chapter, Outline
from models.character import Character, WorldSetting, PlotEvent
from models.enums import (
    NovelStatus, ChapterStatus, CharacterRole, CharacterStatus,
    EventType, EventImportance,
)

logger = logging.getLogger(__name__)

# SQL for creating all tables
_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS novels (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    genre TEXT NOT NULL,
    synopsis TEXT DEFAULT '',
    style_guide TEXT DEFAULT '',
    target_chapter_count INTEGER DEFAULT 0,
    chapters_per_volume INTEGER DEFAULT 30,
    planning_metadata TEXT,
    status TEXT DEFAULT 'planning',
    fanqie_book_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS volumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    volume_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    synopsis TEXT DEFAULT '',
    target_chapters INTEGER DEFAULT 30,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    volume_id INTEGER REFERENCES volumes(id),
    chapter_number INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT,
    char_count INTEGER DEFAULT 0,
    outline TEXT,
    hook TEXT,
    status TEXT DEFAULT 'planned',
    review_score REAL,
    review_notes TEXT,
    revision_count INTEGER DEFAULT 0,
    fanqie_chapter_id TEXT,
    published_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    name TEXT NOT NULL,
    aliases TEXT,
    role TEXT DEFAULT 'supporting',
    description TEXT DEFAULT '',
    background TEXT DEFAULT '',
    abilities TEXT,
    relationships TEXT,
    first_appearance INTEGER,
    status TEXT DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS world_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    parent_id INTEGER REFERENCES world_settings(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plot_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    chapter_number INTEGER,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    resolution_chapter INTEGER,
    importance TEXT DEFAULT 'normal',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL REFERENCES novels(id),
    volume_id INTEGER REFERENCES volumes(id),
    chapter_number INTEGER NOT NULL,
    outline_text TEXT NOT NULL,
    key_scenes TEXT,
    characters_involved TEXT,
    emotional_tone TEXT DEFAULT '',
    hook_type TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Indexes and constraints added via migration (idempotent)
_MIGRATION_SQL = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_chapters_novel_chapter ON chapters(novel_id, chapter_number)",
    "CREATE INDEX IF NOT EXISTS idx_chapters_novel_status ON chapters(novel_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_characters_novel ON characters(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_outlines_novel ON outlines(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_outlines_novel_chapter ON outlines(novel_id, chapter_number)",
    "CREATE INDEX IF NOT EXISTS idx_volumes_novel ON volumes(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_world_settings_novel ON world_settings(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_plot_events_novel ON plot_events(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_plot_events_unresolved ON plot_events(novel_id, resolved)",
    # New columns for volume-aware planning
    "ALTER TABLE novels ADD COLUMN chapters_per_volume INTEGER DEFAULT 30",
    "ALTER TABLE novels ADD COLUMN planning_metadata TEXT",
    # Clean up AUTOINCREMENT tracker so IDs can be reused
    "DELETE FROM sqlite_sequence WHERE name = 'novels'",
]


class Database:
    """SQLite database manager for novel workflow."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(_CREATE_TABLES_SQL)
        self._migrate()

    def _migrate(self):
        """Apply idempotent schema migrations (indexes, constraints)."""
        with self._get_conn() as conn:
            for sql in _MIGRATION_SQL:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError as e:
                    logger.debug("Migration skipped (already applied): %s", e)

    def backup_database(self, target_path: str | Path) -> Path:
        """Create a backup copy of the database.

        Args:
            target_path: Path for the backup file.

        Returns:
            Path to the backup file.
        """
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(self.db_path), str(target))
        logger.info("Database backed up to %s", target)
        return target

    # ---- Novel CRUD ----

    def create_novel(self, novel: Novel) -> int:
        with self._get_conn() as conn:
            # Find lowest available ID starting from 1
            rows = conn.execute("SELECT id FROM novels ORDER BY id").fetchall()
            existing = {r["id"] for r in rows}
            next_id = 1
            while next_id in existing:
                next_id += 1

            cursor = conn.execute(
                "INSERT INTO novels (id, title, genre, synopsis, style_guide, "
                "target_chapter_count, chapters_per_volume, planning_metadata, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (next_id, novel.title, novel.genre, novel.synopsis, novel.style_guide,
                 novel.target_chapter_count, novel.chapters_per_volume,
                 novel.planning_metadata, novel.status.value),
            )
            return next_id

    def get_novel(self, novel_id: int) -> Optional[Novel]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
            if not row:
                return None
            return Novel(
                id=row["id"], title=row["title"], genre=row["genre"],
                synopsis=row["synopsis"], style_guide=row["style_guide"],
                target_chapter_count=row["target_chapter_count"],
                chapters_per_volume=row["chapters_per_volume"] or 30,
                planning_metadata=row["planning_metadata"],
                status=NovelStatus(row["status"]),
                fanqie_book_id=row["fanqie_book_id"],
                created_at=row["created_at"], updated_at=row["updated_at"],
            )

    def update_novel(self, novel: Novel):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE novels SET title=?, genre=?, synopsis=?, style_guide=?, "
                "target_chapter_count=?, chapters_per_volume=?, planning_metadata=?, "
                "status=?, fanqie_book_id=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (novel.title, novel.genre, novel.synopsis, novel.style_guide,
                 novel.target_chapter_count, novel.chapters_per_volume,
                 novel.planning_metadata, novel.status.value,
                 novel.fanqie_book_id, novel.id),
            )

    def delete_novel(self, novel_id: int):
        """Delete a novel and all associated data (chapters, volumes, characters, etc.)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM outlines WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM plot_events WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM characters WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM world_settings WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM volumes WHERE novel_id = ?", (novel_id,))
            conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        logger.info("Novel %d and all associated data deleted", novel_id)

    def list_novels(self) -> list[Novel]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM novels ORDER BY id").fetchall()
            return [
                Novel(
                    id=r["id"], title=r["title"], genre=r["genre"],
                    synopsis=r["synopsis"], status=NovelStatus(r["status"]),
                    style_guide=r["style_guide"],
                    target_chapter_count=r["target_chapter_count"],
                    chapters_per_volume=r["chapters_per_volume"] or 30,
                    planning_metadata=r["planning_metadata"],
                    fanqie_book_id=r["fanqie_book_id"],
                    created_at=r["created_at"], updated_at=r["updated_at"],
                )
                for r in rows
            ]

    # ---- Volume CRUD ----

    def create_volume(self, volume: Volume) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO volumes (novel_id, volume_number, title, synopsis, target_chapters) "
                "VALUES (?, ?, ?, ?, ?)",
                (volume.novel_id, volume.volume_number, volume.title,
                 volume.synopsis, volume.target_chapters),
            )
            return cursor.lastrowid

    def get_volumes(self, novel_id: int) -> list[Volume]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM volumes WHERE novel_id = ? ORDER BY volume_number",
                (novel_id,),
            ).fetchall()
            return [
                Volume(
                    id=r["id"], novel_id=r["novel_id"],
                    volume_number=r["volume_number"], title=r["title"],
                    synopsis=r["synopsis"], target_chapters=r["target_chapters"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    # ---- Chapter CRUD ----

    def create_chapter(self, chapter: Chapter) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO chapters (novel_id, volume_id, chapter_number, title, "
                "content, char_count, outline, hook, status, review_score, "
                "review_notes, revision_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chapter.novel_id, chapter.volume_id, chapter.chapter_number,
                 chapter.title, chapter.content, chapter.char_count,
                 chapter.outline, chapter.hook, chapter.status.value,
                 chapter.review_score, chapter.review_notes, chapter.revision_count),
            )
            return cursor.lastrowid

    def get_chapter(self, novel_id: int, chapter_number: int) -> Optional[Chapter]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? AND chapter_number = ?",
                (novel_id, chapter_number),
            ).fetchone()
            if not row:
                return None
            return self._row_to_chapter(row)

    def get_chapters(self, novel_id: int, status: Optional[ChapterStatus] = None) -> list[Chapter]:
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM chapters WHERE novel_id = ? AND status = ? ORDER BY chapter_number",
                    (novel_id, status.value),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chapters WHERE novel_id = ? ORDER BY chapter_number",
                    (novel_id,),
                ).fetchall()
            return [self._row_to_chapter(r) for r in rows]

    def update_chapter(self, chapter: Chapter):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE chapters SET title=?, content=?, char_count=?, outline=?, "
                "hook=?, status=?, review_score=?, review_notes=?, "
                "revision_count=?, fanqie_chapter_id=?, published_at=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (chapter.title, chapter.content, chapter.char_count,
                 chapter.outline, chapter.hook, chapter.status.value,
                 chapter.review_score, chapter.review_notes,
                 chapter.revision_count, chapter.fanqie_chapter_id,
                 chapter.published_at, chapter.id),
            )

    def get_last_chapter_number(self, novel_id: int) -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT MAX(chapter_number) as max_ch FROM chapters WHERE novel_id = ?",
                (novel_id,),
            ).fetchone()
            return row["max_ch"] or 0

    def _row_to_chapter(self, row) -> Chapter:
        return Chapter(
            id=row["id"], novel_id=row["novel_id"],
            volume_id=row["volume_id"],
            chapter_number=row["chapter_number"], title=row["title"],
            content=row["content"], char_count=row["char_count"],
            outline=row["outline"], hook=row["hook"],
            status=ChapterStatus(row["status"]),
            review_score=row["review_score"],
            review_notes=row["review_notes"],
            revision_count=row["revision_count"],
            fanqie_chapter_id=row["fanqie_chapter_id"],
            published_at=row["published_at"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    # ---- Character CRUD ----

    def create_character(self, character: Character) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO characters (novel_id, name, aliases, role, description, "
                "background, abilities, relationships, first_appearance, status, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (character.novel_id, character.name, character.aliases,
                 character.role.value, character.description, character.background,
                 character.abilities, character.relationships,
                 character.first_appearance, character.status.value, character.notes),
            )
            return cursor.lastrowid

    def get_characters(self, novel_id: int) -> list[Character]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM characters WHERE novel_id = ? ORDER BY id",
                (novel_id,),
            ).fetchall()
            return [
                Character(
                    id=r["id"], novel_id=r["novel_id"], name=r["name"],
                    aliases=r["aliases"], role=CharacterRole(r["role"]),
                    description=r["description"], background=r["background"],
                    abilities=r["abilities"], relationships=r["relationships"],
                    first_appearance=r["first_appearance"],
                    status=CharacterStatus(r["status"]), notes=r["notes"],
                    created_at=r["created_at"], updated_at=r["updated_at"],
                )
                for r in rows
            ]

    def update_character(self, character: Character):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE characters SET name=?, aliases=?, role=?, description=?, "
                "background=?, abilities=?, relationships=?, first_appearance=?, "
                "status=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (character.name, character.aliases, character.role.value,
                 character.description, character.background, character.abilities,
                 character.relationships, character.first_appearance,
                 character.status.value, character.notes, character.id),
            )

    # ---- World Settings CRUD ----

    def create_world_setting(self, setting: WorldSetting) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO world_settings (novel_id, category, name, description, parent_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (setting.novel_id, setting.category, setting.name,
                 setting.description, setting.parent_id),
            )
            return cursor.lastrowid

    def get_world_settings(self, novel_id: int, category: Optional[str] = None) -> list[WorldSetting]:
        with self._get_conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM world_settings WHERE novel_id = ? AND category = ?",
                    (novel_id, category),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM world_settings WHERE novel_id = ?",
                    (novel_id,),
                ).fetchall()
            return [
                WorldSetting(
                    id=r["id"], novel_id=r["novel_id"], category=r["category"],
                    name=r["name"], description=r["description"],
                    parent_id=r["parent_id"], created_at=r["created_at"],
                )
                for r in rows
            ]

    # ---- Plot Events CRUD ----

    def create_plot_event(self, event: PlotEvent) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO plot_events (novel_id, chapter_number, event_type, "
                "description, resolved, resolution_chapter, importance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event.novel_id, event.chapter_number, event.event_type.value,
                 event.description, event.resolved, event.resolution_chapter,
                 event.importance.value),
            )
            return cursor.lastrowid

    def get_unresolved_events(self, novel_id: int) -> list[PlotEvent]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM plot_events WHERE novel_id = ? AND resolved = FALSE "
                "ORDER BY chapter_number",
                (novel_id,),
            ).fetchall()
            return [
                PlotEvent(
                    id=r["id"], novel_id=r["novel_id"],
                    chapter_number=r["chapter_number"],
                    event_type=EventType(r["event_type"]),
                    description=r["description"], resolved=bool(r["resolved"]),
                    resolution_chapter=r["resolution_chapter"],
                    importance=EventImportance(r["importance"]),
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def resolve_plot_event(self, event_id: int, resolution_chapter: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE plot_events SET resolved = TRUE, resolution_chapter = ? WHERE id = ?",
                (resolution_chapter, event_id),
            )

    # ---- Outline CRUD ----

    def create_outline(self, outline: Outline) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO outlines (novel_id, volume_id, chapter_number, "
                "outline_text, key_scenes, characters_involved, emotional_tone, hook_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (outline.novel_id, outline.volume_id, outline.chapter_number,
                 outline.outline_text, outline.key_scenes,
                 outline.characters_involved, outline.emotional_tone,
                 outline.hook_type),
            )
            return cursor.lastrowid

    def get_outline(self, novel_id: int, chapter_number: int) -> Optional[Outline]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM outlines WHERE novel_id = ? AND chapter_number = ?",
                (novel_id, chapter_number),
            ).fetchone()
            if not row:
                return None
            return Outline(
                id=row["id"], novel_id=row["novel_id"],
                volume_id=row["volume_id"],
                chapter_number=row["chapter_number"],
                outline_text=row["outline_text"],
                key_scenes=row["key_scenes"],
                characters_involved=row["characters_involved"],
                emotional_tone=row["emotional_tone"],
                hook_type=row["hook_type"],
                created_at=row["created_at"], updated_at=row["updated_at"],
            )

    def update_outline(self, outline: Outline):
        """Update an existing outline record."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE outlines SET outline_text=?, key_scenes=?, characters_involved=?, "
                "emotional_tone=?, hook_type=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (outline.outline_text, outline.key_scenes, outline.characters_involved,
                 outline.emotional_tone, outline.hook_type, outline.id),
            )

    def get_outlines(self, novel_id: int) -> list[Outline]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM outlines WHERE novel_id = ? ORDER BY chapter_number",
                (novel_id,),
            ).fetchall()
            return [
                Outline(
                    id=r["id"], novel_id=r["novel_id"],
                    volume_id=r["volume_id"],
                    chapter_number=r["chapter_number"],
                    outline_text=r["outline_text"],
                    key_scenes=r["key_scenes"],
                    characters_involved=r["characters_involved"],
                    emotional_tone=r["emotional_tone"],
                    hook_type=r["hook_type"],
                    created_at=r["created_at"], updated_at=r["updated_at"],
                )
                for r in rows
            ]
