"""Short Story Planner Agent: generates structured plans for short stories."""

import logging
from typing import Callable, Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)


class ShortStoryPlannerAgent(BaseAgent):
    """Generates structured plans for short stories including plot, characters, and emotional arc."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("short_story_planner")

    async def plan(
        self,
        genre: str,
        premise: str,
        ideas: str = "",
        target_chars: int = 10000,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Generate a structured short story plan.

        Args:
            genre: Story genre (e.g., '科幻', '悬疑', '言情').
            premise: User-provided story concept/premise.
            ideas: Optional author notes or extra ideas.
            target_chars: Target character count for the finished story.
            on_event: Optional callback for progress events.

        Returns:
            Dict with keys: title, synopsis, characters, plot_outline,
            emotional_arc, category_suggestion, target_chars.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        user_section = self._extract_section(self._template, "规划指令")

        # Calculate recommended chapter count based on target length
        if target_chars <= 5000:
            chapter_count = 1
        elif target_chars <= 15000:
            chapter_count = max(2, target_chars // 5000)
        else:
            chapter_count = max(3, min(5, target_chars // 5000))

        user_prompt = self._safe_format(
            user_section,
            genre=genre,
            premise=premise,
            ideas=ideas or "无",
            target_chars=target_chars,
            chapter_count=chapter_count,
        )

        logger.info(
            "ShortStoryPlannerAgent: planning '%s' story (%d target chars)",
            genre, target_chars,
        )

        result = await self.llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_genre_research,
        )

        # Ensure all expected keys exist with sensible defaults
        result.setdefault("title", "未命名短篇")
        result.setdefault("synopsis", "")
        result.setdefault("characters", [])
        result.setdefault("plot_outline", "")
        result.setdefault("emotional_arc", "")
        result.setdefault("category_suggestion", genre)
        result["target_chars"] = target_chars

        logger.info(
            "ShortStoryPlannerAgent: plan complete — '%s', %d characters defined",
            result["title"],
            len(result["characters"]),
        )

        return result
