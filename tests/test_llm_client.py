"""Tests for JSON parsing utilities and AgentSDKClient."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from claude_agent_sdk import ResultMessage, AssistantMessage, TextBlock


def _make_result_message(result_text: str) -> ResultMessage:
    """Helper to create a ResultMessage with required fields."""
    return ResultMessage(
        subtype="result",
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        session_id="test-session",
        total_cost_usd=0.001,
        usage={"input_tokens": 10, "output_tokens": 20},
        result=result_text,
        structured_output=None,
    )


def _make_assistant_message(text: str) -> AssistantMessage:
    """Helper to create an AssistantMessage with a text block."""
    return AssistantMessage(
        content=[TextBlock(text=text)],
        model="claude-sonnet-4-6",
        parent_tool_use_id=None,
        error=None,
    )


class TestParseJsonResponse:
    def test_direct_json(self):
        from tools.llm_client import parse_json_response
        result = parse_json_response('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_markdown_code_fence_with_lang(self):
        from tools.llm_client import parse_json_response
        text = '```json\n{"key": "value"}\n```'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_markdown_code_fence_without_lang(self):
        from tools.llm_client import parse_json_response
        text = '```\n{"key": "value"}\n```'
        result = parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_embedded_in_prose(self):
        from tools.llm_client import parse_json_response
        text = '以下是结果：{"score": 8.5, "passed": true}，供参考。'
        result = parse_json_response(text)
        assert result["score"] == 8.5
        assert result["passed"] is True

    def test_invalid_raises_value_error(self):
        from tools.llm_client import parse_json_response
        with pytest.raises(ValueError, match="Failed to parse"):
            parse_json_response("这根本不是JSON格式的内容abc")

    def test_empty_object(self):
        from tools.llm_client import parse_json_response
        result = parse_json_response("{}")
        assert result == {}

    def test_json_array(self):
        from tools.llm_client import parse_json_response
        result = parse_json_response('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_nested_json(self):
        from tools.llm_client import parse_json_response
        result = parse_json_response('{"a": {"b": [1, 2]}}')
        assert result["a"]["b"] == [1, 2]

    def test_json_with_surrounding_whitespace(self):
        from tools.llm_client import parse_json_response
        result = parse_json_response('  \n  {"key": "value"}  \n  ')
        assert result == {"key": "value"}


class TestAgentSDKClient:
    @pytest.mark.asyncio
    async def test_chat_returns_result_text(self):
        """Test that chat() returns the result from query()."""
        mock_message = _make_result_message("Hello from Claude")

        async def mock_query(*args, **kwargs):
            yield mock_message

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            result = await client.chat("system prompt", "user prompt")
            assert result == "Hello from Claude"
            assert client.total_calls == 1

    @pytest.mark.asyncio
    async def test_chat_json_parses_response(self):
        """Test that chat_json() parses JSON from the response."""
        mock_message = _make_result_message('{"title": "测试", "score": 9.5}')

        async def mock_query(*args, **kwargs):
            yield mock_message

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            result = await client.chat_json("system", "user")
            assert result["title"] == "测试"
            assert result["score"] == 9.5

    @pytest.mark.asyncio
    async def test_chat_json_raises_on_invalid_json(self):
        """Test that chat_json() raises LLMResponseParseError on bad JSON."""
        from config.exceptions import LLMResponseParseError

        mock_message = _make_result_message("not valid json at all")

        async def mock_query(*args, **kwargs):
            yield mock_message

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            with pytest.raises(LLMResponseParseError):
                await client.chat_json("system", "user")

    @pytest.mark.asyncio
    async def test_chat_with_tools_returns_result(self):
        """Test that chat_with_tools() returns the final result."""
        mock_message = _make_result_message('{"score": 8.0, "issues": []}')

        async def mock_query(*args, **kwargs):
            yield mock_message

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            result = await client.chat_with_tools("system", "user", max_turns=5)
            assert '"score"' in result

    @pytest.mark.asyncio
    async def test_chat_raises_llm_error_on_exception(self):
        """Test that chat() wraps exceptions in LLMError."""
        from config.exceptions import LLMError

        async def mock_query(*args, **kwargs):
            raise RuntimeError("Connection failed")
            yield  # Make it an async generator

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            with pytest.raises(LLMError, match="Connection failed"):
                await client.chat("system", "user")

    def test_get_usage_summary(self):
        """Test that usage summary returns total_calls."""
        with patch("tools.agent_sdk_client.query"):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            client.total_calls = 5
            summary = client.get_usage_summary()
            assert summary["total_calls"] == 5

    @pytest.mark.asyncio
    async def test_chat_returns_empty_on_no_result(self):
        """Test that chat() returns empty string when no result message."""
        async def mock_query(*args, **kwargs):
            return
            yield  # Make it an async generator

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            result = await client.chat("system", "user")
            assert result == ""

    @pytest.mark.asyncio
    async def test_chat_fallback_to_assistant_message(self):
        """Test that chat() falls back to AssistantMessage content when no ResultMessage."""
        mock_assistant = _make_assistant_message("Fallback text content")

        async def mock_query(*args, **kwargs):
            yield mock_assistant

        with patch("tools.agent_sdk_client.query", mock_query):
            from tools.agent_sdk_client import AgentSDKClient
            client = AgentSDKClient()
            result = await client.chat("system", "user")
            assert result == "Fallback text content"
