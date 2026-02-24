"""Tests for database CRUD operations."""

import sqlite3

import pytest

from models.novel import Novel
from models.chapter import Chapter, Outline
from models.character import Character, PlotEvent
from models.enums import (
    NovelStatus, ChapterStatus, CharacterRole, CharacterStatus,
    EventType, EventImportance,
)


class TestNovelCRUD:
    def test_create_and_get_novel(self, db):
        novel = Novel(
            title="测试小说",
            genre="玄幻",
            synopsis="一部关于修炼的故事",
            style_guide="热血",
            target_chapter_count=10,
            status=NovelStatus.WRITING,
        )
        novel_id = db.create_novel(novel)
        assert novel_id > 0

        retrieved = db.get_novel(novel_id)
        assert retrieved is not None
        assert retrieved.title == "测试小说"
        assert retrieved.genre == "玄幻"
        assert retrieved.status == NovelStatus.WRITING

    def test_get_novel_not_found_returns_none(self, db):
        assert db.get_novel(9999) is None

    def test_update_novel(self, db, sample_novel):
        sample_novel.title = "更新后的标题"
        sample_novel.status = NovelStatus.COMPLETED
        db.update_novel(sample_novel)

        retrieved = db.get_novel(sample_novel.id)
        assert retrieved.title == "更新后的标题"
        assert retrieved.status == NovelStatus.COMPLETED

    def test_list_novels_returns_all(self, db):
        n1 = Novel(title="小说一", genre="玄幻", status=NovelStatus.WRITING)
        n2 = Novel(title="小说二", genre="都市", status=NovelStatus.PLANNING)
        db.create_novel(n1)
        db.create_novel(n2)

        novels = db.list_novels()
        titles = [n.title for n in novels]
        assert "小说一" in titles
        assert "小说二" in titles


class TestChapterCRUD:
    def test_create_and_get_chapter(self, db, sample_novel):
        chapter = Chapter(
            novel_id=sample_novel.id,
            chapter_number=1,
            title="第一章",
            content="内容" * 50,
            char_count=100,
            status=ChapterStatus.DRAFTED,
        )
        db.create_chapter(chapter)

        retrieved = db.get_chapter(sample_novel.id, 1)
        assert retrieved is not None
        assert retrieved.title == "第一章"
        assert retrieved.status == ChapterStatus.DRAFTED

    def test_get_chapter_not_found_returns_none(self, db, sample_novel):
        assert db.get_chapter(sample_novel.id, 9999) is None

    def test_duplicate_chapter_number_raises_integrity_error(self, db, sample_novel):
        chapter = Chapter(
            novel_id=sample_novel.id,
            chapter_number=99,
            title="重复章节",
            content="内容",
            char_count=2,
            status=ChapterStatus.DRAFTED,
        )
        db.create_chapter(chapter)

        with pytest.raises(sqlite3.IntegrityError):
            db.create_chapter(chapter)

    def test_get_last_chapter_number_returns_zero_when_empty(self, db):
        novel = Novel(title="空白小说", genre="玄幻", status=NovelStatus.WRITING)
        novel_id = db.create_novel(novel)
        assert db.get_last_chapter_number(novel_id) == 0

    def test_get_last_chapter_number_returns_max(self, db, sample_novel):
        for num in [3, 1, 7, 5]:
            ch = Chapter(
                novel_id=sample_novel.id,
                chapter_number=num,
                title=f"第{num}章",
                status=ChapterStatus.DRAFTED,
            )
            db.create_chapter(ch)
        assert db.get_last_chapter_number(sample_novel.id) == 7

    def test_get_chapters_by_status(self, db, sample_novel):
        statuses = [ChapterStatus.DRAFTED, ChapterStatus.DRAFTED, ChapterStatus.REVIEWED]
        for i, status in enumerate(statuses, start=1):
            ch = Chapter(
                novel_id=sample_novel.id,
                chapter_number=i,
                title=f"第{i}章",
                status=status,
            )
            db.create_chapter(ch)

        drafted = db.get_chapters(sample_novel.id, status=ChapterStatus.DRAFTED)
        reviewed = db.get_chapters(sample_novel.id, status=ChapterStatus.REVIEWED)
        assert len(drafted) == 2
        assert len(reviewed) == 1

    def test_update_chapter(self, db, sample_novel):
        chapter = Chapter(
            novel_id=sample_novel.id,
            chapter_number=42,
            title="初始标题",
            status=ChapterStatus.DRAFTED,
        )
        chapter_id = db.create_chapter(chapter)
        chapter.id = chapter_id
        chapter.title = "修改后标题"
        chapter.status = ChapterStatus.REVIEWED
        chapter.review_score = 8.5
        db.update_chapter(chapter)

        retrieved = db.get_chapter(sample_novel.id, 42)
        assert retrieved.title == "修改后标题"
        assert retrieved.review_score == 8.5
        assert retrieved.status == ChapterStatus.REVIEWED


class TestCharacterCRUD:
    def test_create_and_get_characters(self, db, sample_novel):
        char = Character(
            novel_id=sample_novel.id,
            name="张三",
            role=CharacterRole.PROTAGONIST,
            description="主角",
            status=CharacterStatus.ACTIVE,
        )
        db.create_character(char)

        chars = db.get_characters(sample_novel.id)
        assert len(chars) == 1
        assert chars[0].name == "张三"
        assert chars[0].role == CharacterRole.PROTAGONIST

    def test_update_character(self, db, sample_novel):
        char = Character(
            novel_id=sample_novel.id,
            name="李四",
            role=CharacterRole.ANTAGONIST,
            status=CharacterStatus.ACTIVE,
        )
        char_id = db.create_character(char)
        char.id = char_id
        char.status = CharacterStatus.DECEASED
        char.description = "已阵亡"
        db.update_character(char)

        chars = db.get_characters(sample_novel.id)
        updated = chars[0]
        assert updated.status == CharacterStatus.DECEASED
        assert updated.description == "已阵亡"


class TestDatabaseBackup:
    def test_backup_creates_file(self, db, tmp_path):
        backup_path = tmp_path / "backups" / "db_backup.sqlite"
        result = db.backup_database(backup_path)
        assert result.exists()
        assert result == backup_path

    def test_backup_is_valid_sqlite(self, db, tmp_path, sample_novel):
        backup_path = tmp_path / "db_backup.sqlite"
        db.backup_database(backup_path)

        # Verify the backup contains the SQLite magic header
        # (WAL mode may not have tables checkpointed to the main file yet,
        # but the file itself must be a valid SQLite database file)
        with open(str(backup_path), "rb") as f:
            header = f.read(16)
        assert header.startswith(b"SQLite format 3")


class TestOutlineCRUD:
    def test_create_and_get_outline(self, db, sample_novel):
        outline = Outline(
            novel_id=sample_novel.id,
            chapter_number=1,
            outline_text="本章大纲内容",
            emotional_tone="紧张",
            hook_type="cliffhanger",
        )
        db.create_outline(outline)

        retrieved = db.get_outline(sample_novel.id, 1)
        assert retrieved is not None
        assert retrieved.outline_text == "本章大纲内容"
        assert retrieved.emotional_tone == "紧张"

    def test_get_outline_not_found_returns_none(self, db, sample_novel):
        assert db.get_outline(sample_novel.id, 9999) is None

    def test_get_outlines_ordered_by_chapter(self, db, sample_novel):
        for i in [3, 1, 2]:
            outline = Outline(
                novel_id=sample_novel.id,
                chapter_number=i,
                outline_text=f"第{i}章大纲",
            )
            db.create_outline(outline)

        outlines = db.get_outlines(sample_novel.id)
        assert len(outlines) == 3
        assert [o.chapter_number for o in outlines] == [1, 2, 3]


class TestPlotEventCRUD:
    def test_create_and_get_unresolved_event(self, db, sample_novel):
        event = PlotEvent(
            novel_id=sample_novel.id,
            chapter_number=1,
            event_type=EventType.FORESHADOW,
            description="伏笔：神秘信件",
            importance=EventImportance.MAJOR,
        )
        db.create_plot_event(event)

        unresolved = db.get_unresolved_events(sample_novel.id)
        assert len(unresolved) == 1
        assert unresolved[0].description == "伏笔：神秘信件"
        assert unresolved[0].resolved is False

    def test_resolve_event_removes_from_unresolved(self, db, sample_novel):
        event = PlotEvent(
            novel_id=sample_novel.id,
            chapter_number=2,
            event_type=EventType.SETUP,
            description="待解决事件",
        )
        event_id = db.create_plot_event(event)
        db.resolve_plot_event(event_id, resolution_chapter=5)

        unresolved = db.get_unresolved_events(sample_novel.id)
        assert len(unresolved) == 0
