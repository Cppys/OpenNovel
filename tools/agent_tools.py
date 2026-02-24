"""Custom tool definitions for Claude Agent SDK.

These tools are defined using the @tool decorator and registered into an
in-process MCP server. They are passed to the ReviewerAgent for agentic
quality checking.
"""

import json

from claude_agent_sdk import tool, create_sdk_mcp_server


@tool("count_chinese_chars", "统计文本中的中文字符数量，检查是否在目标范围内。", {"text": str})
async def count_chinese_chars_tool(args):
    """Count Chinese characters and check if within target range."""
    from tools.text_utils import count_chinese_chars
    from config.settings import Settings

    text = args["text"]
    s = Settings()
    count = count_chinese_chars(text)
    result = json.dumps({
        "char_count": count,
        "min_required": s.chapter_min_chars,
        "max_allowed": s.chapter_max_chars,
        "in_range": s.chapter_min_chars <= count <= s.chapter_max_chars,
    }, ensure_ascii=False)
    return {"content": [{"type": "text", "text": result}]}


@tool("check_typos", "检查中文文本中的错别字和同音字错误。", {"text": str})
async def check_typos_tool(args):
    """Check for common Chinese typos and errors."""
    from tools.typo_checker import check_typos

    text = args["text"]
    issues = check_typos(text)
    result = json.dumps([
        {
            "position": t.position,
            "original": t.original,
            "suggestion": t.suggestion,
            "reason": t.reason,
        }
        for t in issues[:5]
    ], ensure_ascii=False)
    return {"content": [{"type": "text", "text": result}]}


@tool("check_ai_patterns", "检测文本中常见的 AI 生成写作痕迹。", {"text": str})
async def check_ai_patterns_tool(args):
    """Check for common AI writing patterns."""
    from tools.typo_checker import check_ai_patterns

    text = args["text"]
    result = json.dumps(check_ai_patterns(text), ensure_ascii=False)
    return {"content": [{"type": "text", "text": result}]}


@tool("check_punctuation", "检查中文文本中的标点符号错误。", {"text": str})
async def check_punctuation_tool(args):
    """Check for punctuation issues in Chinese text."""
    from tools.typo_checker import check_punctuation

    text = args["text"]
    issues = check_punctuation(text)
    result = json.dumps([
        {
            "position": p.position,
            "original": p.original,
            "suggestion": p.suggestion,
            "reason": p.reason,
        }
        for p in issues[:3]
    ], ensure_ascii=False)
    return {"content": [{"type": "text", "text": result}]}


@tool("analyze_writing_style", "分析文本的写作风格指标（对话比例、句式方差、段落结构等）。", {"text": str})
async def analyze_writing_style_tool(args):
    """Analyze writing style metrics."""
    from tools.style_analyzer import analyze_style

    text = args["text"]
    report = analyze_style(text)
    result = json.dumps({
        "dialogue_ratio": report.dialogue_ratio,
        "sentence_length_std": report.sentence_length_std,
        "unique_starters_ratio": report.unique_starters_ratio,
        "paragraph_count": report.paragraph_count,
        "issues": report.issues,
        "style_score": report.score,
    }, ensure_ascii=False)
    return {"content": [{"type": "text", "text": result}]}


def get_review_tools_server():
    """Create an MCP server with all review tools registered.

    Returns:
        McpSdkServerConfig for use with ClaudeAgentOptions.mcp_servers.
    """
    return create_sdk_mcp_server(
        name="novel-review-tools",
        version="1.0.0",
        tools=[
            count_chinese_chars_tool,
            check_typos_tool,
            check_ai_patterns_tool,
            check_punctuation_tool,
            analyze_writing_style_tool,
        ],
    )
