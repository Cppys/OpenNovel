"""Tests for custom @tool functions."""

import json
import pytest


class TestCountChineseCharsTool:
    @pytest.mark.asyncio
    async def test_counts_chinese_chars(self):
        from tools.agent_tools import count_chinese_chars_tool
        raw = await count_chinese_chars_tool.handler({"text": "你好世界"})
        result = json.loads(raw["content"][0]["text"])
        assert result["char_count"] == 4

    @pytest.mark.asyncio
    async def test_empty_string(self):
        from tools.agent_tools import count_chinese_chars_tool
        raw = await count_chinese_chars_tool.handler({"text": ""})
        result = json.loads(raw["content"][0]["text"])
        assert result["char_count"] == 0

    @pytest.mark.asyncio
    async def test_mixed_content(self):
        from tools.agent_tools import count_chinese_chars_tool
        raw = await count_chinese_chars_tool.handler({"text": "Hello你好World世界"})
        result = json.loads(raw["content"][0]["text"])
        assert result["char_count"] == 4

    @pytest.mark.asyncio
    async def test_below_range(self):
        from tools.agent_tools import count_chinese_chars_tool
        raw = await count_chinese_chars_tool.handler({"text": "你好"})
        result = json.loads(raw["content"][0]["text"])
        assert result["in_range"] is False


class TestCheckTyposTool:
    @pytest.mark.asyncio
    async def test_detects_common_typo(self):
        from tools.agent_tools import check_typos_tool
        raw = await check_typos_tool.handler({"text": "高兴的跑"})
        result = json.loads(raw["content"][0]["text"])
        assert len(result) > 0
        assert result[0]["original"] == "高兴的跑"
        assert "地" in result[0]["suggestion"]

    @pytest.mark.asyncio
    async def test_clean_text_returns_empty(self):
        from tools.agent_tools import check_typos_tool
        raw = await check_typos_tool.handler({"text": "他高兴地跑了"})
        result = json.loads(raw["content"][0]["text"])
        assert len(result) == 0


class TestCheckAiPatternsTool:
    @pytest.mark.asyncio
    async def test_detects_ai_pattern(self):
        from tools.agent_tools import check_ai_patterns_tool
        raw = await check_ai_patterns_tool.handler({"text": "一股强大的力量涌入体内"})
        result = json.loads(raw["content"][0]["text"])
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_no_patterns_returns_empty(self):
        from tools.agent_tools import check_ai_patterns_tool
        raw = await check_ai_patterns_tool.handler({"text": "他静静地站在窗前"})
        result = json.loads(raw["content"][0]["text"])
        assert len(result) == 0


class TestCheckPunctuationTool:
    @pytest.mark.asyncio
    async def test_detects_english_comma_in_chinese(self):
        from tools.agent_tools import check_punctuation_tool
        raw = await check_punctuation_tool.handler({"text": "你好,世界"})
        result = json.loads(raw["content"][0]["text"])
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_correct_punctuation_returns_empty(self):
        from tools.agent_tools import check_punctuation_tool
        raw = await check_punctuation_tool.handler({"text": "你好，世界。"})
        result = json.loads(raw["content"][0]["text"])
        assert len(result) == 0


class TestAnalyzeWritingStyleTool:
    @pytest.mark.asyncio
    async def test_returns_expected_keys(self):
        from tools.agent_tools import analyze_writing_style_tool
        text = "这是第一段内容。\n\n" + "\u201c你好！\u201d他说。\n\n" + "故事继续发展。"
        raw = await analyze_writing_style_tool.handler({"text": text})
        result = json.loads(raw["content"][0]["text"])
        assert "dialogue_ratio" in result
        assert "sentence_length_std" in result
        assert "unique_starters_ratio" in result
        assert "paragraph_count" in result
        assert "style_score" in result
        assert "issues" in result

    @pytest.mark.asyncio
    async def test_empty_text(self):
        from tools.agent_tools import analyze_writing_style_tool
        raw = await analyze_writing_style_tool.handler({"text": ""})
        result = json.loads(raw["content"][0]["text"])
        assert result["paragraph_count"] == 0


class TestGetReviewToolsServer:
    def test_creates_server_config(self):
        from tools.agent_tools import get_review_tools_server
        server = get_review_tools_server()
        assert server is not None
