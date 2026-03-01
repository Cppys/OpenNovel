"""Short Story Reviewer Agent: multi-dimensional quality assessment for short stories."""

import logging
import re
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient
from tools.llm_client import parse_json_response
from tools.text_utils import count_chinese_chars

logger = logging.getLogger(__name__)


class ShortStoryReviewerAgent(BaseAgent):
    """Performs multi-dimensional quality review on short stories.

    Uses a single LLM call to evaluate writing quality, plot coherence,
    character depth, and overall literary merit.
    """

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("short_story_reviewer")

    async def review(
        self,
        title: str,
        content: str,
        char_count: int,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Review a short story across multiple quality dimensions.

        Args:
            title: Story title.
            content: The complete short story text.
            char_count: Pre-computed Chinese character count.
            on_event: Optional callback for progress events.

        Returns:
            Dict with keys: passed (bool), score (float), issues (list), summary (str).
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        review_section = self._extract_section(self._template, "审核指令")

        target_min = int(char_count * 0.8)
        target_max = int(char_count * 1.2)

        user_prompt = self._safe_format(
            review_section,
            story_title=title,
            chapter_info="单章短篇",
            content=content,
            char_count=char_count,
            target_min=target_min,
            target_max=target_max,
            story_plan="（参见上文内容）",
            previous_content="（无）",
        )

        logger.info(
            "ShortStoryReviewerAgent: reviewing '%s' (%d chars)...",
            title, char_count,
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
            logger.warning("LLM review failed: %s. Using fallback score.", e)
            result = self._programmatic_review(content, char_count)

        score = min(10.0, max(0.0, result.get("score", 5.0)))
        issues = result.get("issues", [])

        critical_count = sum(1 for i in issues if i.get("severity") == "critical")
        passed = score >= 7.0 and critical_count == 0

        logger.info(
            "ShortStoryReviewerAgent: review complete — score=%.1f, passed=%s, "
            "issues=%d (critical=%d)",
            score, passed, len(issues), critical_count,
        )

        return {
            "passed": passed,
            "score": score,
            "issues": issues,
            "summary": result.get("summary", ""),
        }

    def _programmatic_review(self, content: str, char_count: int) -> dict:
        """Fallback review when LLM call fails -- heuristic checks."""
        issues = []
        score = 8.0

        # --- Word count ---
        if char_count < 1000:
            issues.append({
                "category": "字数",
                "severity": "critical",
                "description": f"字数严重不足：{char_count}字",
                "suggestion": "短篇小说建议至少1000字以上",
            })
            score -= 2.0
        elif char_count < 3000:
            issues.append({
                "category": "字数",
                "severity": "minor",
                "description": f"字数偏少：{char_count}字",
                "suggestion": "可适当扩写以丰富细节",
            })
            score -= 0.5

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
        eng_quotes = len(re.findall(r'[""\'\'"]', content))
        if eng_quotes > 0:
            issues.append({
                "category": "标点",
                "severity": "major",
                "description": f"发现{eng_quotes}处英文引号或无方向引号，应使用中文引号\u201c\u201d\u2018\u2019",
                "suggestion": "将所有英文引号替换为中文引号（左\u201c右\u201d必须配对）",
            })
            score -= 0.5

        # Chinese quotes not paired
        left_dq = content.count("\u201c")
        right_dq = content.count("\u201d")
        if left_dq != right_dq:
            issues.append({
                "category": "标点",
                "severity": "major",
                "description": f"中文双引号不配对：左引号\u201c{left_dq}个，右引号\u201d{right_dq}个",
                "suggestion": "检查每个对话的引号是否左右配对（\u201c开头，\u201d结尾）",
            })
            score -= 0.5

        # Wrong ellipsis
        bad_ellipsis = len(re.findall(r'\.{3,}|。{2,}', content))
        if bad_ellipsis > 0:
            issues.append({
                "category": "标点",
                "severity": "minor",
                "description": f"发现{bad_ellipsis}处非标准省略号，应使用'……'",
                "suggestion": "统一使用中文省略号'……'（六个点）",
            })
            score -= 0.2

        # Consecutive exclamation/question marks
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
            long_paras = sum(1 for p in paragraphs if count_chinese_chars(p) > 200)
            if long_paras > 2:
                issues.append({
                    "category": "段落",
                    "severity": "minor",
                    "description": f"有{long_paras}个段落超过200字，段落过长影响阅读节奏",
                    "suggestion": "拆分长段落，保持长短交替的节奏感",
                })
                score -= 0.3

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
