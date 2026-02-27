"""Configuration settings loaded from .env file."""

from pathlib import Path
from typing import Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, loaded from .env file.

    API key and base URL are no longer needed — Claude Agent SDK
    handles authentication automatically via Claude Code CLI.
    Temperature is not configurable in Agent SDK (guided via system_prompt).
    Rate limiting is handled by the SDK itself.
    """

    # LLM Models — one per agent role
    llm_model_writing: str = "claude-opus-4-6"         # WriterAgent
    llm_model_editing: str = "claude-opus-4-6"         # EditorAgent
    llm_model_reviewing: str = "claude-opus-4-6"       # ReviewerAgent
    llm_model_genre_research: str = "claude-opus-4-6"  # GenreResearchAgent
    llm_model_story_architect: str = "claude-opus-4-6" # StoryArchitectAgent
    llm_model_conflict_design: str = "claude-opus-4-6" # ConflictDesignAgent
    llm_model_memory: str = "claude-haiku-4-5"         # MemoryManagerAgent / Summarizer

    # Database
    sqlite_db_path: Path = Path("./data/novels.db")
    chroma_persist_dir: Path = Path("./data/chroma")

    # Browser
    browser_user_data_dir: Path = Path("./data/browser_profile")
    auth_state_path: Path = Path("./data/auth_state.json")

    # Publishing
    default_publish_mode: str = "draft"
    declare_ai_content: bool = True

    # Chapter
    chapter_min_chars: int = 2050
    chapter_max_chars: int = 3000
    max_revisions: int = 3

    # Memory
    global_review_interval: int = 5
    context_max_chars: int = 3000

    # Context compression
    context_compression_threshold: int = 20000  # Max formatted conversation chars before compression

    # Logging
    log_dir: Path = Path("./data/logs")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @field_validator("max_revisions")
    @classmethod
    def validate_max_revisions(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_revisions must be >= 1")
        return v

    @field_validator("global_review_interval")
    @classmethod
    def validate_review_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("global_review_interval must be >= 1")
        return v

    @field_validator("chapter_min_chars", "chapter_max_chars")
    @classmethod
    def validate_char_counts(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Character count must be non-negative")
        return v

    @field_validator("sqlite_db_path", "chroma_persist_dir", "browser_user_data_dir", "log_dir")
    @classmethod
    def ensure_parent_dirs(cls, v: Path) -> Path:
        v.parent.mkdir(parents=True, exist_ok=True)
        return v

    @model_validator(mode="after")
    def validate_char_range(self) -> "Settings":
        if self.chapter_min_chars >= self.chapter_max_chars:
            raise ValueError(
                f"chapter_min_chars ({self.chapter_min_chars}) must be less than "
                f"chapter_max_chars ({self.chapter_max_chars})"
            )
        return self


_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance
