"""Tests for Agent classes and BaseAgent utilities."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


# Minimal prompt templates covering all format placeholders used by each agent

_WRITER_TEMPLATE = """\
## System Prompt
你是专业写作助手。

## 核心写作原则
遵循写作规范，保持一致性。

## 创作指令
请为第{chapter_number}章创作内容。类型：{genre}。风格：{style_guide}。
前情：{context_prompt}。上章结尾：{previous_chapter_ending}。
本章大纲：{chapter_outline}。情感：{emotional_tone}。结尾方式：{hook_type}。
字数：{min_chars}至{max_chars}字。
"""

_EDITOR_TEMPLATE = """\
## System Prompt
你是专业编辑。

## 编辑指令
请编辑以下章节（共{char_count}字）。目标字数：{target_min}-{target_max}字。
大纲：{chapter_outline}。
内容：{chapter_content}
"""

_REVIEWER_TEMPLATE = """\
## System Prompt
你是专业审核员。

## 审核指令
请审核以下章节（共{char_count}字）。大纲：{chapter_outline}。
上下文：{context_prompt}。目标字数：{target_min}-{target_max}字。
内容：{chapter_content}
"""

_PLANNER_TEMPLATE = """\
## System Prompt
你是专业策划员。

## 大纲生成指令
请为{genre}类型小说生成大纲。设定：{premise}
"""

_SECTION_TEMPLATE = """\
## System Prompt
这是系统提示内容。

## 其他章节
这是其他章节的内容，不应出现在System Prompt节的提取结果中。

## 最后一节
最后内容。
"""


class TestBaseAgent:
    def _make_agent(self, mock_llm, settings):
        from agents.base_agent import BaseAgent
        return BaseAgent(llm_client=mock_llm, settings=settings)

    def test_extract_section_returns_correct_content(self, mock_llm, settings):
        agent = self._make_agent(mock_llm, settings)
        result = agent._extract_section(_SECTION_TEMPLATE, "System Prompt")
        assert "系统提示内容" in result

    def test_extract_section_not_found_returns_empty_string(self, mock_llm, settings):
        agent = self._make_agent(mock_llm, settings)
        result = agent._extract_section(_SECTION_TEMPLATE, "不存在的章节名称")
        assert result == ""

    def test_extract_section_stops_at_next_header(self, mock_llm, settings):
        agent = self._make_agent(mock_llm, settings)
        result = agent._extract_section(_SECTION_TEMPLATE, "System Prompt")
        # Content from the next section must not bleed through
        assert "其他章节的内容" not in result
        assert "最后内容" not in result

    def test_extract_last_section_captures_to_end(self, mock_llm, settings):
        agent = self._make_agent(mock_llm, settings)
        result = agent._extract_section(_SECTION_TEMPLATE, "最后一节")
        assert "最后内容" in result

    def test_load_prompt_raises_file_not_found_for_missing_template(self, mock_llm, settings):
        agent = self._make_agent(mock_llm, settings)
        with pytest.raises(FileNotFoundError):
            agent._load_prompt("nonexistent_template_xyz_123")


class TestWriterAgent:
    @pytest.mark.asyncio
    async def test_write_chapter_returns_expected_keys(self, mock_llm, settings):
        mock_llm.chat = AsyncMock(return_value=(
            "【标题】\n第一章：觉醒\n\n【正文】\n"
            + "这是测试章节内容。" * 20
        ))

        with patch("agents.base_agent._read_prompt_file", return_value=_WRITER_TEMPLATE):
            from agents.writer_agent import WriterAgent
            writer = WriterAgent(llm_client=mock_llm, settings=settings)
            result = await writer.write_chapter(
                genre="玄幻",
                style_guide="热血",
                chapter_number=1,
                chapter_outline="主角觉醒力量，击败反派",
                context_prompt="无前情提要",
            )

        assert "title" in result
        assert "content" in result
        assert "char_count" in result

    @pytest.mark.asyncio
    async def test_write_chapter_uses_default_title_when_llm_omits_it(self, mock_llm, settings):
        # No markers — entire text treated as content
        mock_llm.chat = AsyncMock(return_value="纯正文内容无标记")

        with patch("agents.base_agent._read_prompt_file", return_value=_WRITER_TEMPLATE):
            from agents.writer_agent import WriterAgent
            writer = WriterAgent(llm_client=mock_llm, settings=settings)
            result = await writer.write_chapter(
                genre="都市",
                style_guide="",
                chapter_number=3,
                chapter_outline="主角与朋友相遇",
                context_prompt="",
            )

        assert result["title"] == "第3章"
        assert result["content"] == "纯正文内容无标记"

    @pytest.mark.asyncio
    async def test_write_chapter_char_count_reflects_chinese_chars(self, mock_llm, settings):
        # "你好世界" = 4 Chinese chars × 25 = 100 chars
        mock_llm.chat = AsyncMock(return_value=(
            "【标题】\n第二章\n\n【正文】\n" + "你好世界" * 25
        ))

        with patch("agents.base_agent._read_prompt_file", return_value=_WRITER_TEMPLATE):
            from agents.writer_agent import WriterAgent
            writer = WriterAgent(llm_client=mock_llm, settings=settings)
            result = await writer.write_chapter(
                genre="玄幻",
                style_guide="",
                chapter_number=2,
                chapter_outline="测试大纲",
                context_prompt="",
            )

        assert result["char_count"] == 100

    @pytest.mark.asyncio
    async def test_write_chapter_passes_correct_args_to_llm(self, mock_llm, settings):
        mock_llm.chat = AsyncMock(return_value="【标题】\n标题\n\n【正文】\n内容")

        with patch("agents.base_agent._read_prompt_file", return_value=_WRITER_TEMPLATE):
            from agents.writer_agent import WriterAgent
            writer = WriterAgent(llm_client=mock_llm, settings=settings)
            await writer.write_chapter(
                genre="玄幻",
                style_guide="热血",
                chapter_number=1,
                chapter_outline="大纲",
                context_prompt="上下文",
            )

        # LLM must have been called exactly once
        assert mock_llm.chat.call_count == 1


class TestEditorAgent:
    @pytest.mark.asyncio
    async def test_edit_chapter_returns_expected_keys(self, mock_llm, settings):
        mock_llm.chat = AsyncMock(return_value=(
            "【编辑说明】\n修改了语句流畅度\n\n【正文】\n"
            + "编辑后的内容" * 20
        ))

        with patch("agents.base_agent._read_prompt_file", return_value=_EDITOR_TEMPLATE):
            from agents.editor_agent import EditorAgent
            editor = EditorAgent(llm_client=mock_llm, settings=settings)
            result = await editor.edit_chapter(
                chapter_content="原始内容" * 20,
                chapter_outline="测试大纲",
                char_count=80,
            )

        assert "content" in result
        assert "char_count" in result
        assert "edit_notes" in result


class TestPlannerAgent:
    @pytest.mark.asyncio
    async def test_generate_outline_returns_expected_keys(self, mock_llm, settings):
        mock_llm.chat = AsyncMock(return_value=(
            "【书名】\n逆天修仙路\n\n"
            "【简介】\n少年觉醒\n\n"
            "【风格指南】\n热血\n\n"
            "【角色列表】\n主角|protagonist|少年|背景|能力|成长\n\n"
            "【世界设定】\n\n"
            "【第1卷】第一卷\n概述\n\n"
            "===第1章===\n大纲：开篇\n场景：场景1\n角色：主角\n情感：热血\n钩子：cliffhanger\n"
        ))

        with patch("agents.base_agent._read_prompt_file", return_value=_PLANNER_TEMPLATE):
            from agents.planner_agent import PlannerAgent
            planner = PlannerAgent(llm_client=mock_llm, settings=settings)
            result = await planner.generate_outline(
                genre="玄幻",
                premise="少年偶获传承",
            )

        assert result["title"] == "逆天修仙路"
        assert len(result["characters"]) == 1

    @pytest.mark.asyncio
    async def test_generate_outline_sets_defaults(self, mock_llm, settings):
        mock_llm.chat = AsyncMock(return_value="无标记的纯文本")

        with patch("agents.base_agent._read_prompt_file", return_value=_PLANNER_TEMPLATE):
            from agents.planner_agent import PlannerAgent
            planner = PlannerAgent(llm_client=mock_llm, settings=settings)
            result = await planner.generate_outline(
                genre="都市",
                premise="都市奇才",
            )

        assert result["title"] == "未命名小说"
        assert result["genre"] == "都市"
        assert result["characters"] == []


class TestReviewerAgent:
    @pytest.mark.asyncio
    async def test_review_chapter_returns_expected_keys(self, mock_llm, settings):
        mock_llm.chat_with_tools = AsyncMock(
            return_value='{"score": 8.5, "issues": [], "summary": "章节质量良好"}'
        )
        # 120 Chinese chars — within test settings (min=100, max=200)
        content = "这是测试内容，有一定字数。" * 10

        with patch("agents.base_agent._read_prompt_file", return_value=_REVIEWER_TEMPLATE):
            from agents.reviewer_agent import ReviewerAgent
            reviewer = ReviewerAgent(llm_client=mock_llm, settings=settings)
            result = await reviewer.review_chapter(
                chapter_content=content,
                chapter_outline="测试大纲",
            )

        assert "passed" in result
        assert "score" in result
        assert "issues" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_review_chapter_score_capped_at_10(self, mock_llm, settings):
        mock_llm.chat_with_tools = AsyncMock(
            return_value='{"score": 15.0, "issues": [], "summary": "极好"}'
        )
        content = "你好世界啊" * 30  # 150 chars, within range

        with patch("agents.base_agent._read_prompt_file", return_value=_REVIEWER_TEMPLATE):
            from agents.reviewer_agent import ReviewerAgent
            reviewer = ReviewerAgent(llm_client=mock_llm, settings=settings)
            result = await reviewer.review_chapter(
                chapter_content=content,
                chapter_outline="大纲",
            )

        assert result["score"] <= 10.0

    @pytest.mark.asyncio
    async def test_review_chapter_passes_when_score_high(self, mock_llm, settings):
        mock_llm.chat_with_tools = AsyncMock(
            return_value='{"score": 9.0, "issues": [], "summary": "优秀"}'
        )
        content = "你好世界啊" * 30  # 150 chars

        with patch("agents.base_agent._read_prompt_file", return_value=_REVIEWER_TEMPLATE):
            from agents.reviewer_agent import ReviewerAgent
            reviewer = ReviewerAgent(llm_client=mock_llm, settings=settings)
            result = await reviewer.review_chapter(
                chapter_content=content,
                chapter_outline="大纲",
            )

        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_review_chapter_fails_on_critical_issues(self, mock_llm, settings):
        mock_llm.chat_with_tools = AsyncMock(
            return_value='{"score": 8.0, "issues": [{"severity": "critical", "description": "严重问题"}], "summary": "有问题"}'
        )
        content = "你好世界啊" * 30

        with patch("agents.base_agent._read_prompt_file", return_value=_REVIEWER_TEMPLATE):
            from agents.reviewer_agent import ReviewerAgent
            reviewer = ReviewerAgent(llm_client=mock_llm, settings=settings)
            result = await reviewer.review_chapter(
                chapter_content=content,
                chapter_outline="大纲",
            )

        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_review_chapter_fallback_on_exception(self, mock_llm, settings):
        mock_llm.chat_with_tools = AsyncMock(
            side_effect=Exception("LLM unavailable")
        )
        content = "你好世界啊" * 30

        with patch("agents.base_agent._read_prompt_file", return_value=_REVIEWER_TEMPLATE):
            from agents.reviewer_agent import ReviewerAgent
            reviewer = ReviewerAgent(llm_client=mock_llm, settings=settings)
            result = await reviewer.review_chapter(
                chapter_content=content,
                chapter_outline="大纲",
            )

        # Should fallback gracefully
        assert "score" in result
        assert result["score"] == 7.0
