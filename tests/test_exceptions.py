"""Tests for the custom exception hierarchy."""

import pytest
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


class TestExceptionHierarchy:
    def test_all_inherit_from_novel_agent_error(self):
        leaf_classes = [
            LLMError, LLMRateLimitError, LLMTimeoutError, LLMResponseParseError,
            DatabaseError,
            PublisherError, LoginRequiredError, PageElementNotFoundError,
            WorkflowError, WorkflowStateError, WorkflowMaxRevisionsError,
            ValidationError, ChapterLengthError, InvalidConfigError,
        ]
        for cls in leaf_classes:
            assert issubclass(cls, NovelAgentError), f"{cls.__name__} must inherit NovelAgentError"

    def test_llm_subclasses(self):
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMTimeoutError, LLMError)
        assert issubclass(LLMResponseParseError, LLMError)

    def test_publisher_subclasses(self):
        assert issubclass(LoginRequiredError, PublisherError)
        assert issubclass(PageElementNotFoundError, PublisherError)

    def test_workflow_subclasses(self):
        assert issubclass(WorkflowStateError, WorkflowError)
        assert issubclass(WorkflowMaxRevisionsError, WorkflowError)

    def test_validation_subclasses(self):
        assert issubclass(ChapterLengthError, ValidationError)
        assert issubclass(InvalidConfigError, ValidationError)


class TestExceptionCreation:
    def test_basic_message(self):
        err = LLMError("API failed")
        assert err.message == "API failed"
        assert err.details == {}

    def test_with_details(self):
        err = LLMRateLimitError("Rate limited", retry_after=60)
        assert err.details["retry_after"] == 60

    def test_str_representation(self):
        err = LLMTimeoutError("Request timed out")
        assert "timed out" in str(err)

    def test_parse_error_has_raw_response(self):
        err = LLMResponseParseError("Parse failed", raw_response='{"bad": json}')
        assert err.raw_response == '{"bad": json}'

    def test_catchable_as_exception(self):
        with pytest.raises(NovelAgentError):
            raise WorkflowStateError("Bad state")

    def test_catchable_as_specific_type(self):
        with pytest.raises(LLMRateLimitError):
            raise LLMRateLimitError("429")
