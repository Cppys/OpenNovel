"""Custom exception hierarchy for the novel agent workflow."""

from typing import Optional


class NovelAgentError(Exception):
    """Base exception for all novel agent errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message


# ---- LLM Errors ----

class LLMError(NovelAgentError):
    """Base exception for LLM API errors."""


class LLMRateLimitError(LLMError):
    """LLM API rate limit exceeded."""

    def __init__(self, message: str = "API rate limit exceeded", retry_after: Optional[float] = None):
        details = {}
        if retry_after is not None:
            details["retry_after"] = retry_after
        super().__init__(message, details)
        self.retry_after = retry_after


class LLMTimeoutError(LLMError):
    """LLM API request timed out."""


class LLMResponseParseError(LLMError):
    """Failed to parse LLM response."""

    def __init__(self, message: str = "Failed to parse LLM response", raw_response: str = ""):
        details = {"raw_response": raw_response[:200]} if raw_response else {}
        super().__init__(message, details)
        self.raw_response = raw_response


# ---- Database Errors ----

class DatabaseError(NovelAgentError):
    """Database operation failed."""


# ---- Publisher Errors ----

class PublisherError(NovelAgentError):
    """Base exception for publisher/browser automation errors."""


class LoginRequiredError(PublisherError):
    """User login is required but not completed."""

    def __init__(self, message: str = "Login required"):
        super().__init__(message)


class PageElementNotFoundError(PublisherError):
    """Expected page element not found during browser automation."""

    def __init__(self, selector: str, message: str = ""):
        msg = message or f"Element not found: {selector}"
        super().__init__(msg, {"selector": selector})
        self.selector = selector


# ---- Workflow Errors ----

class WorkflowError(NovelAgentError):
    """Base exception for workflow orchestration errors."""


class WorkflowStateError(WorkflowError):
    """Invalid or missing workflow state."""


class WorkflowMaxRevisionsError(WorkflowError):
    """Maximum revision count exceeded."""

    def __init__(self, chapter: int, revision_count: int, max_revisions: int):
        super().__init__(
            f"Chapter {chapter} exceeded max revisions",
            {"chapter": chapter, "revision_count": revision_count, "max_revisions": max_revisions},
        )


# ---- Validation Errors ----

class ValidationError(NovelAgentError):
    """Input validation failed."""


class ChapterLengthError(ValidationError):
    """Chapter length out of acceptable range."""

    def __init__(self, actual: int, min_chars: int, max_chars: int):
        super().__init__(
            f"Chapter length {actual} chars outside range [{min_chars}, {max_chars}]",
            {"actual": actual, "min": min_chars, "max": max_chars},
        )


class InvalidConfigError(ValidationError):
    """Configuration value is invalid."""
