"""Tests for Settings validation."""

import pytest
from pydantic import ValidationError


class TestSettingsDefaults:
    def test_settings_created_with_defaults(self, settings):
        assert settings.chapter_min_chars == 100
        assert settings.chapter_max_chars == 200

    def test_default_max_revisions(self, settings):
        assert settings.max_revisions == 2

    def test_default_global_review_interval(self, settings):
        assert settings.global_review_interval == 3

    def test_default_model_names(self, settings):
        from config.settings import Settings
        # Use _env_file=None to test code defaults without .env overrides
        s = Settings(
            _env_file=None,
            sqlite_db_path=settings.sqlite_db_path,
            chroma_persist_dir=settings.chroma_persist_dir,
            log_dir=settings.log_dir,
            browser_user_data_dir=settings.browser_user_data_dir,
            chapter_min_chars=100,
            chapter_max_chars=200,
        )
        assert s.llm_model_writing == "claude-opus-4-6"
        assert s.llm_model_editing == "claude-opus-4-6"
        assert s.llm_model_planning == "claude-opus-4-6"


class TestSettingsValidation:
    def test_min_chars_gte_max_chars_raises(self, tmp_path):
        from config.settings import Settings
        with pytest.raises(ValidationError, match="[Cc]har"):
            Settings(
                sqlite_db_path=tmp_path / "novels.db",
                chroma_persist_dir=tmp_path / "chroma",
                log_dir=tmp_path / "logs",
                browser_user_data_dir=tmp_path / "browser",
                chapter_min_chars=500,
                chapter_max_chars=300,
            )

    def test_max_revisions_zero_raises(self, tmp_path):
        from config.settings import Settings
        with pytest.raises(ValidationError, match="max_revisions"):
            Settings(
                sqlite_db_path=tmp_path / "novels.db",
                chroma_persist_dir=tmp_path / "chroma",
                log_dir=tmp_path / "logs",
                browser_user_data_dir=tmp_path / "browser",
                chapter_min_chars=100,
                chapter_max_chars=200,
                max_revisions=0,
            )

    def test_global_review_interval_zero_raises(self, tmp_path):
        from config.settings import Settings
        with pytest.raises(ValidationError, match="global_review_interval"):
            Settings(
                sqlite_db_path=tmp_path / "novels.db",
                chroma_persist_dir=tmp_path / "chroma",
                log_dir=tmp_path / "logs",
                browser_user_data_dir=tmp_path / "browser",
                chapter_min_chars=100,
                chapter_max_chars=200,
                global_review_interval=0,
            )

    def test_negative_char_count_raises(self, tmp_path):
        from config.settings import Settings
        with pytest.raises(ValidationError, match="[Cc]haracter"):
            Settings(
                sqlite_db_path=tmp_path / "novels.db",
                chroma_persist_dir=tmp_path / "chroma",
                log_dir=tmp_path / "logs",
                browser_user_data_dir=tmp_path / "browser",
                chapter_min_chars=-1,
                chapter_max_chars=200,
            )

    def test_equal_min_max_raises(self, tmp_path):
        from config.settings import Settings
        with pytest.raises(ValidationError, match="[Cc]har"):
            Settings(
                sqlite_db_path=tmp_path / "novels.db",
                chroma_persist_dir=tmp_path / "chroma",
                log_dir=tmp_path / "logs",
                browser_user_data_dir=tmp_path / "browser",
                chapter_min_chars=200,
                chapter_max_chars=200,
            )

    def test_valid_settings_accepted(self, tmp_path):
        from config.settings import Settings
        s = Settings(
            sqlite_db_path=tmp_path / "novels.db",
            chroma_persist_dir=tmp_path / "chroma",
            log_dir=tmp_path / "logs",
            browser_user_data_dir=tmp_path / "browser",
            chapter_min_chars=100,
            chapter_max_chars=200,
            max_revisions=3,
            global_review_interval=5,
        )
        assert s.chapter_min_chars == 100
        assert s.chapter_max_chars == 200
        assert s.max_revisions == 3

    def test_path_parent_dirs_created(self, tmp_path):
        from config.settings import Settings
        deep_path = tmp_path / "a" / "b" / "c" / "novels.db"
        s = Settings(
            sqlite_db_path=deep_path,
            chroma_persist_dir=tmp_path / "chroma",
            log_dir=tmp_path / "logs",
            browser_user_data_dir=tmp_path / "browser",
            chapter_min_chars=100,
            chapter_max_chars=200,
        )
        assert deep_path.parent.exists()
