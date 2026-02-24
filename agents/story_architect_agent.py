"""Story Architect Agent: designs characters, world settings, volumes, and plot backbone."""

import logging
import math
from typing import Optional

from agents.base_agent import BaseAgent
from agents.planner_agent import (
    _extract_section,
    _parse_pipe_lines,
    _VOLUME_RE,
)
from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)


class StoryArchitectAgent(BaseAgent):
    """Designs the full story architecture: characters, world, volumes, and plot backbone."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        super().__init__(llm_client, settings)
        self._template = self._load_prompt("story_architect")

    async def design(
        self,
        genre: str,
        premise: str,
        ideas: str,
        target_chapters: int,
        genre_research: dict,
        chapters_per_volume: int = 30,
    ) -> dict:
        """Design the story architecture.

        Args:
            genre: Novel genre.
            premise: Story premise.
            ideas: Author notes.
            target_chapters: Total target chapter count.
            genre_research: Output from GenreResearchAgent.
            chapters_per_volume: Chapters per volume.

        Returns:
            Dict with keys: title, synopsis, style_guide, characters,
            world_settings, volumes (with synopsis, no chapters), plot_backbone.
        """
        num_volumes = math.ceil(target_chapters / chapters_per_volume)

        system_prompt = self._extract_section(self._template, "System Prompt")
        user_prompt = self._extract_section(self._template, "故事架构指令")
        user_prompt = user_prompt.replace("{genre}", genre)
        user_prompt = user_prompt.replace("{premise}", premise)
        user_prompt = user_prompt.replace("{ideas}", ideas or "无")
        user_prompt = user_prompt.replace("{target_chapters}", str(target_chapters))
        user_prompt = user_prompt.replace("{chapters_per_volume}", str(chapters_per_volume))
        user_prompt = user_prompt.replace("{num_volumes}", str(num_volumes))

        # Format genre research as readable text
        research_text = self._format_research(genre_research)
        user_prompt = user_prompt.replace("{genre_research}", research_text)

        logger.info("StoryArchitectAgent: designing architecture for '%s'", premise[:50])

        raw_text = await self.llm.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.llm_model_planning,
        )

        result = self._parse_architecture(raw_text, premise)

        logger.info(
            "StoryArchitectAgent: completed — %d characters, %d world settings, %d volumes",
            len(result.get("characters", [])),
            len(result.get("world_settings", [])),
            len(result.get("volumes", [])),
        )
        return result

    @staticmethod
    def _format_research(research: dict) -> str:
        """Format genre research dict into readable text for the prompt."""
        lines = []
        lines.append(f"核心套路: {research.get('genre_conventions', '')}")
        tropes = research.get("recommended_tropes", [])
        if tropes:
            lines.append(f"推荐桥段: {', '.join(tropes)}")
        lines.append(f"读者期待: {research.get('reader_expectations', '')}")
        lines.append(f"节奏建议: {research.get('pacing_guidelines', '')}")
        lines.append(f"差异化卖点: {research.get('differentiation', '')}")
        lines.append(f"黄金三章策略: {research.get('golden_three_strategy', '')}")
        return "\n".join(lines)

    @staticmethod
    def _parse_architecture(text: str, premise: str) -> dict:
        """Parse the architect's structured text output."""
        title = _extract_section(text, "书名") or premise
        synopsis = _extract_section(text, "简介")
        style_guide = _extract_section(text, "风格指南")
        plot_backbone = _extract_section(text, "主线骨架")

        # Characters
        char_section = _extract_section(text, "角色列表")
        characters = []
        for parts in _parse_pipe_lines(char_section, 6):
            characters.append({
                "name": parts[0],
                "role": parts[1],
                "description": parts[2],
                "background": parts[3],
                "abilities": parts[4],
                "arc": parts[5],
            })

        # World settings
        ws_section = _extract_section(text, "世界设定")
        world_settings = []
        for parts in _parse_pipe_lines(ws_section, 3):
            world_settings.append({
                "category": parts[0],
                "name": parts[1],
                "description": parts[2],
            })

        # Volumes (synopsis only, no chapters)
        volumes = []
        vol_matches = list(_VOLUME_RE.finditer(text))
        # Stop at 【主线骨架】 if present
        backbone_start = text.find("【主线骨架】")

        for i, vol_match in enumerate(vol_matches):
            vol_num = int(vol_match.group(1))
            vol_title = vol_match.group(2).strip()

            start = vol_match.end()
            if i + 1 < len(vol_matches):
                end = vol_matches[i + 1].start()
            elif backbone_start > start:
                end = backbone_start
            else:
                end = len(text)

            vol_text = text[start:end].strip()
            # Volume synopsis is everything in the volume section (no chapters here)
            # Remove any trailing 【...】 markers
            import re
            vol_synopsis = re.split(r"\n【", vol_text)[0].strip()

            volumes.append({
                "volume_number": vol_num,
                "title": vol_title,
                "synopsis": vol_synopsis,
            })

        return {
            "title": title,
            "synopsis": synopsis,
            "style_guide": style_guide,
            "characters": characters,
            "world_settings": world_settings,
            "volumes": volumes,
            "plot_backbone": plot_backbone,
        }
