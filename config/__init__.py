"""Configuration package — settings, logging, and exceptions."""

from config.exceptions import (
    NovelAgentError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMResponseParseError,
    DatabaseError,
    PublisherError,
    LoginRequiredError,
    PageElementNotFoundError,
    WorkflowError,
    WorkflowStateError,
    WorkflowMaxRevisionsError,
    ValidationError,
    ChapterLengthError,
    InvalidConfigError,
)
from config.logging_config import setup_logging
from config.settings import Settings, get_settings

__all__ = [
    "Settings",
    "get_settings",
    "setup_logging",
    "NovelAgentError",
    "LLMError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMResponseParseError",
    "DatabaseError",
    "PublisherError",
    "LoginRequiredError",
    "PageElementNotFoundError",
    "WorkflowError",
    "WorkflowStateError",
    "WorkflowMaxRevisionsError",
    "ValidationError",
    "ChapterLengthError",
    "InvalidConfigError",
]
