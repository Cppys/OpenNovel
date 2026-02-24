"""Base agent class with common LLM and prompt utilities."""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

from config.settings import Settings
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "config" / "prompts"


@lru_cache(maxsize=32)
def _read_prompt_file(path: str) -> str:
    """Read and cache a prompt file by absolute path string."""
    return Path(path).read_text(encoding="utf-8")


class BaseAgent:
    """Base class for all agents in the workflow."""

    def __init__(
        self,
        llm_client: Optional[AgentSDKClient] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or Settings()
        self.llm = llm_client or AgentSDKClient(self.settings)

    def _load_prompt(self, template_name: str) -> str:
        """Load a prompt template from config/prompts/ (cached after first read).

        Args:
            template_name: Filename without extension, e.g. 'writer'.

        Returns:
            The prompt template text.
        """
        path = _PROMPTS_DIR / f"{template_name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return _read_prompt_file(str(path))

    def _extract_section(self, template: str, section_header: str) -> str:
        """Extract a specific section from a prompt template.

        Sections are delimited by '## ' headers in the markdown.
        """
        lines = template.split("\n")
        capturing = False
        result = []
        for line in lines:
            if line.strip().startswith("## ") and section_header in line:
                capturing = True
                continue
            elif line.strip().startswith("## ") and capturing:
                break
            elif capturing:
                result.append(line)
        return "\n".join(result).strip()
