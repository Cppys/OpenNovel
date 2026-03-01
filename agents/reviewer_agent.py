"""Reviewer Agent: multi-dimensional chapter quality assessment."""

import logging
import re
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient
from tools.llm_client import parse_json_response
from tools.text_utils import count_chinese_chars

logger = logging.getLogger(__name__)


class ReviewerAgent(BaseAgent):
    """Performs multi-dimensional quality review on chapters.

    Uses a single LLM call to evaluate writing quality, consistency,
    and adherence to the outline.
    """

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("reviewer")

    async def review_chapter(
        self,
        chapter_content: str,
        chapter_outline: str,
        context_prompt: str = "",
        char_count: Optional[int] = None,
        chapter_title: str = "",
        chapter_number: int = 0,
        existing_titles: str = "",
        previous_ending: str = "",
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Review a chapter across multiple quality dimensions.

        Args:
            chapter_content: The edited chapter text.
            chapter_outline: Original outline for reference.
            context_prompt: Memory context for consistency checking.
            char_count: Pre-computed character count (computed if not provided).
            previous_ending: The ending text of the previous chapter for coherence checking.

        Returns:
            Dict with keys: passed, score, issues, summary.
        """
        if char_count is None:
            char_count = count_chinese_chars(chapter_content)

        system_prompt = self._extract_section(self._template, "System Prompt")
        system_prompt += """

请从以下维度审核章节质量：
1. **标题质量**（critical级别）：
   - 标题是否包含"第X章"字样？（绝对禁止——系统会自动添加章节号前缀，否则会出现"第37章 第37章 xxx"）
   - 标题是否与已有章节标题重复？（绝对禁止——番茄平台不允许重复标题，上传会失败）
   - 标题是否有吸引力、与本章核心情节相关？空洞的标题（如"新的开始""风波"）视为 major 问题
2. **前后文连贯性**（critical级别）：
   - 与上一章结尾是否自然衔接？情节、场景、情绪是否连贯？
   - 是否符合当前卷的整体主题和走向？是否遵循大纲方向？
   - 角色状态（位置、情绪、关系）是否与前文一致？
3. 字数是否达标
4. 是否紧扣大纲，情节完整
5. 文笔流畅度、对话自然度
6. 是否有AI写作痕迹（如模式化开头、过度使用"突然"、段落结构过于规律等）
7. 标点符号：是否全部使用中文全角标点？对话是否使用""？省略号是否为"……"？破折号是否为"——"？是否有连续感叹号/问号？
8. 段落排版：段落长短是否有变化？是否有超长段落？多人对话是否独立成段？连续多段是否以相同词语开头？

请严格遵守评审标准，保持客观公正。
输出严格JSON格式（不要加```json标记）：
{"score": 0-10, "issues": [{"category": "标题|连贯性|字数|情节|文笔|AI痕迹|标点|段落", "severity": "critical|major|minor", "description": "...", "suggestion": "..."}], "summary": "一句话总评"}
"""

        title_info = ""
        if chapter_title:
            title_info = f"\n章节标题：{chapter_title}\n章节编号：第{chapter_number}章\n"
        if existing_titles:
            title_info += f"已有章节标题列表（检查重复用）：\n{existing_titles}\n"

        # Build previous chapter ending section for coherence check
        prev_ending_section = ""
        if previous_ending:
            prev_ending_section = (
                f"\n\n**【上一章结尾原文（连贯性审查核心依据）】**\n"
                f"以下是上一章的最后部分，请仔细对比当前章节开头是否自然衔接：\n"
                f"---\n{previous_ending}\n---\n"
                f"请重点检查：\n"
                f"1. 当前章节开头是否承接了上一章的场景/情绪/对话？\n"
                f"2. 角色的位置、状态、情绪是否与上一章结尾一致？\n"
                f"3. 时间线是否连续？是否有突兀的跳跃？\n"
                f"如发现连贯性问题，必须标记为 critical 级别。\n"
            )

        user_prompt = (
            f"请审核以下章节（当前{char_count}字，"
            f"目标{self.settings.chapter_min_chars}-{self.settings.chapter_max_chars}字）：\n"
            f"{title_info}\n"
            f"{chapter_content}\n\n"
            f"大纲：{chapter_outline}\n"
            f"上下文：{context_prompt or '（无前文上下文）'}"
            f"{prev_ending_section}"
        )

        try:
            result_text = await self.llm.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.settings.llm_model_reviewing,
                on_event=on_event,
            )

            result = parse_json_response(result_text)
        except Exception as e:
            logger.warning(f"LLM review failed: {e}. Using fallback score.")
            result = self._programmatic_review(chapter_content, char_count)

        score = min(10.0, max(0.0, result.get("score", 5.0)))
        issues = result.get("issues", [])

        # Post-processing: enforce critical severity for coherence issues
        # The LLM may underrate coherence problems; ensure they block passage
        coherence_categories = {"连贯性", "coherence", "consistency", "逻辑一致性"}
        for issue in issues:
            cat = issue.get("category", "").lower()
            if any(cc in cat for cc in coherence_categories):
                if issue.get("severity") != "critical":
                    logger.info(
                        "Elevating coherence issue to critical: %s",
                        issue.get("description", "")[:80],
                    )
                    issue["severity"] = "critical"

        critical_count = sum(1 for i in issues if i.get("severity") == "critical")
        passed = score >= 6.0 and critical_count == 0

        logger.info(
            f"Review complete: score={score:.1f}, passed={passed}, "
            f"issues={len(issues)} (critical={critical_count})"
        )

        return {
            "passed": passed,
            "score": score,
            "issues": issues,
            "summary": result.get("summary", ""),
        }

    def _programmatic_review(self, content: str, char_count: int) -> dict:
        """Fallback review when LLM call fails — heuristic checks."""
        issues = []
        score = 8.0

        # --- Word count ---
        if char_count < self.settings.chapter_min_chars:
            deficit = self.settings.chapter_min_chars - char_count
            issues.append({
                "category": "字数",
                "severity": "critical" if deficit > 500 else "major",
                "description": f"字数不足：{char_count}字，低于最低要求{self.settings.chapter_min_chars}字",
                "suggestion": f"需扩写约{deficit}字",
            })
            score -= 2.0 if deficit > 500 else 1.0
        elif char_count > self.settings.chapter_max_chars:
            excess = char_count - self.settings.chapter_max_chars
            issues.append({
                "category": "字数",
                "severity": "major",
                "description": f"字数超标：{char_count}字，超过上限{self.settings.chapter_max_chars}字",
                "suggestion": f"需精简约{excess}字",
            })
            score -= 1.0

        # --- AI pattern markers ---
        ai_markers = ["突然", "不由自主", "情不自禁", "此刻", "就在这时",
                       "在这一刻", "一股强大的气息", "神秘的力量"]
        for marker in ai_markers:
            count = content.count(marker)
            threshold = 1 if marker == "突然" else 2
            if count > threshold:
                issues.append({
                    "category": "AI痕迹",
                    "severity": "major" if count > 3 else "minor",
                    "description": f"'{marker}'出现{count}次，疑似AI写作痕迹",
                    "suggestion": "减少使用或替换为更自然的表达",
                })
                score -= 0.5 if count > 3 else 0.3

        # --- Punctuation checks ---
        # English quotes in Chinese text
        eng_quotes = len(re.findall(r'[""\'\'"]', content))
        if eng_quotes > 0:
            issues.append({
                "category": "标点",
                "severity": "major",
                "description": f"发现{eng_quotes}处英文引号或无方向引号，应使用中文引号\u201c\u201d\u2018\u2019",
                "suggestion": "将所有英文引号替换为中文引号（左\u201c右\u201d必须配对）",
            })
            score -= 0.5

        # Chinese quotes not paired (mismatched left/right)
        left_dq = content.count("\u201c")   # "
        right_dq = content.count("\u201d")  # "
        if left_dq != right_dq:
            issues.append({
                "category": "标点",
                "severity": "major",
                "description": f"中文双引号不配对：左引号\u201c{left_dq}个，右引号\u201d{right_dq}个",
                "suggestion": "检查每个对话的引号是否左右配对（\u201c开头，\u201d结尾）",
            })
            score -= 0.5

        left_sq = content.count("\u2018")   # '
        right_sq = content.count("\u2019")  # '
        if left_sq != right_sq:
            issues.append({
                "category": "标点",
                "severity": "minor",
                "description": f"中文单引号不配对：左引号\u2018{left_sq}个，右引号\u2019{right_sq}个",
                "suggestion": "检查单引号是否左右配对（\u2018开头，\u2019结尾）",
            })
            score -= 0.2

        # Wrong ellipsis (... or 。。。 instead of ……)
        bad_ellipsis = len(re.findall(r'\.{3,}|。{2,}', content))
        if bad_ellipsis > 0:
            issues.append({
                "category": "标点",
                "severity": "minor",
                "description": f"发现{bad_ellipsis}处非标准省略号，应使用'……'",
                "suggestion": "统一使用中文省略号'……'（六个点）",
            })
            score -= 0.2

        # Consecutive exclamation/question marks (！！！ or ？？？)
        repeated_punct = len(re.findall(r'[！!]{2,}|[？?]{2,}', content))
        if repeated_punct > 0:
            issues.append({
                "category": "标点",
                "severity": "minor",
                "description": f"发现{repeated_punct}处连续感叹号/问号",
                "suggestion": "每处最多使用一个感叹号或问号",
            })
            score -= 0.2

        # --- Paragraph checks ---
        paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
        if paragraphs:
            # Oversized paragraphs (> 200 Chinese chars)
            long_paras = sum(1 for p in paragraphs if count_chinese_chars(p) > 200)
            if long_paras > 2:
                issues.append({
                    "category": "段落",
                    "severity": "minor",
                    "description": f"有{long_paras}个段落超过200字，段落过长影响阅读节奏",
                    "suggestion": "拆分长段落，保持长短交替的节奏感",
                })
                score -= 0.3

            # Repetitive paragraph openings (3+ consecutive paragraphs starting with same char)
            if len(paragraphs) >= 3:
                streak = 1
                max_streak = 1
                for i in range(1, len(paragraphs)):
                    if paragraphs[i][0] == paragraphs[i - 1][0]:
                        streak += 1
                        max_streak = max(max_streak, streak)
                    else:
                        streak = 1
                if max_streak >= 3:
                    issues.append({
                        "category": "段落",
                        "severity": "minor",
                        "description": f"连续{max_streak}个段落以相同字开头，句式单调",
                        "suggestion": "变换段落开头的词语和句式",
                    })
                    score -= 0.3

        score = max(3.0, min(10.0, score))
        summary = f"程序化审核：{len(issues)}个问题，评分{score:.1f}"

        return {"score": score, "issues": issues, "summary": summary}
