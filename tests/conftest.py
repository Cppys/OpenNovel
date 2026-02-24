"""Shared pytest fixtures for the opennovel test suite."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db_path(tmp_path):
    """Return a temporary SQLite database path."""
    return tmp_path / "test_novels.db"


@pytest.fixture
def db(tmp_db_path):
    """Return an initialized Database instance backed by a temp file."""
    from models.database import Database
    return Database(tmp_db_path)


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def settings(tmp_path):
    """Return a Settings instance with all paths pointing to tmp_path."""
    from config.settings import Settings
    return Settings(
        sqlite_db_path=tmp_path / "novels.db",
        chroma_persist_dir=tmp_path / "chroma",
        log_dir=tmp_path / "logs",
        browser_user_data_dir=tmp_path / "browser",
        chapter_min_chars=100,
        chapter_max_chars=200,
        max_revisions=2,
        global_review_interval=3,
    )


# ---------------------------------------------------------------------------
# LLM Client mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm():
    """Return a MagicMock replacing AgentSDKClient (sync-compatible for non-async tests)."""
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="这是一段测试内容。" * 20)
    llm.chat_json = AsyncMock(return_value={"passed": True, "score": 8.5, "summary": "Good"})
    llm.chat_with_tools = AsyncMock(return_value='{"score": 8.0, "issues": [], "summary": "good"}')
    llm.get_usage_summary.return_value = {
        "total_calls": 1,
    }
    llm.settings = MagicMock()
    llm.settings.llm_model_writing = "claude-opus-4-6"
    llm.settings.llm_model_editing = "claude-opus-4-6"
    llm.settings.llm_model_reviewing = "claude-opus-4-6"
    llm.settings.llm_model_genre_research = "claude-opus-4-6"
    llm.settings.llm_model_story_architect = "claude-opus-4-6"
    llm.settings.llm_model_conflict_design = "claude-opus-4-6"
    llm.settings.llm_model_memory = "claude-haiku-4-5"
    llm.settings.chapter_min_chars = 100
    llm.settings.chapter_max_chars = 200
    return llm


@pytest.fixture
def mock_agent_sdk():
    """Return a fully-configured AsyncMock for AgentSDKClient."""
    llm = AsyncMock()
    llm.chat.return_value = "test response"
    llm.chat_json.return_value = {"title": "测试", "content": "内容"}
    llm.chat_with_tools.return_value = '{"score": 8.0, "issues": [], "summary": "good"}'
    llm.get_usage_summary.return_value = {"total_calls": 1}
    llm.settings = MagicMock()
    llm.settings.llm_model_writing = "claude-opus-4-6"
    llm.settings.llm_model_editing = "claude-opus-4-6"
    llm.settings.llm_model_reviewing = "claude-opus-4-6"
    llm.settings.llm_model_genre_research = "claude-opus-4-6"
    llm.settings.llm_model_story_architect = "claude-opus-4-6"
    llm.settings.llm_model_conflict_design = "claude-opus-4-6"
    llm.settings.llm_model_memory = "claude-haiku-4-5"
    llm.settings.chapter_min_chars = 100
    llm.settings.chapter_max_chars = 200
    return llm


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_novel(db):
    """Insert and return a sample Novel record."""
    from models.novel import Novel
    from models.enums import NovelStatus
    novel = Novel(
        title="测试小说",
        genre="玄幻",
        synopsis="这是一本测试小说的简介",
        style_guide="轻松明快",
        target_chapter_count=5,
        status=NovelStatus.WRITING,
    )
    novel.id = db.create_novel(novel)
    return novel


@pytest.fixture
def sample_chapter(db, sample_novel):
    """Insert and return a sample Chapter record."""
    from models.chapter import Chapter
    from models.enums import ChapterStatus
    chapter = Chapter(
        novel_id=sample_novel.id,
        chapter_number=1,
        title="第一章：测试章节",
        content="这是章节内容。" * 50,
        char_count=250,
        status=ChapterStatus.REVIEWED,
        review_score=8.0,
    )
    db.create_chapter(chapter)
    return chapter
