"""Genre Research Agent: analyzes genre conventions, reader expectations, and golden-three strategy."""

import logging
from typing import Optional

from agents.base_agent import BaseAgent
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)


class GenreResearchAgent(BaseAgent):
    """Analyzes genre conventions, tropes, reader expectations, and differentiation."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("genre_research")

    async def analyze(self, genre: str, premise: str, ideas: str = "") -> dict:
        """Run genre research analysis.

        Args:
            genre: Novel genre (e.g., '玄幻', '豪门总裁').
            premise: User-provided story concept.
            ideas: Optional author notes.

        Returns:
            Dict with keys: genre_conventions, recommended_tropes,
            reader_expectations, pacing_guidelines, differentiation,
            golden_three_strategy.
        """
        system_prompt = self._extract_section(self._template, "System Prompt")
        user_prompt = self._extract_section(self._template, "类型研究指令")
        user_prompt = user_prompt.replace("{genre}", genre)
        user_prompt = user_prompt.replace("{premise}", premise)
        user_prompt = user_prompt.replace("{ideas}", ideas or "无")

        logger.info("GenreResearchAgent: analyzing genre '%s'", genre)

        result = await self.llm.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_planning,
        )

        # Ensure all expected keys exist
        result.setdefault("genre_conventions", "")
        result.setdefault("recommended_tropes", [])
        result.setdefault("reader_expectations", "")
        result.setdefault("pacing_guidelines", "")
        result.setdefault("differentiation", "")
        result.setdefault("golden_three_strategy", "")

        logger.info(
            "GenreResearchAgent: completed — %d tropes identified",
            len(result["recommended_tropes"]),
        )
        return result
