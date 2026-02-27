"""Claude Agent SDK wrapper, replacing LLMClient."""

import logging
import os
import shutil
import sys
from typing import Callable, Optional

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
    AssistantMessage,
)

from config.settings import Settings
from tools.llm_client import parse_json_response
from config.exceptions import LLMError, LLMResponseParseError

logger = logging.getLogger(__name__)

# Allow launching Agent SDK even when running inside a Claude Code session.
# The SDK checks for this env var and refuses to start if set.
os.environ.pop("CLAUDECODE", None)

# On Windows the bundled Claude Code CLI needs git-bash.
# Auto-detect if CLAUDE_CODE_GIT_BASH_PATH is not already set.
if sys.platform == "win32" and not os.environ.get("CLAUDE_CODE_GIT_BASH_PATH"):
    # Check well-known git-bash locations first
    _candidates = [
        r"D:\git\usr\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
    ]
    # Also try shutil.which, but skip WSL/Windows-Apps bash
    _which = shutil.which("bash")
    if _which and "System32" not in _which and "WindowsApps" not in _which:
        _candidates.insert(0, _which)

    for _p in _candidates:
        if os.path.exists(_p):
            os.environ["CLAUDE_CODE_GIT_BASH_PATH"] = _p
            logger.debug("Set CLAUDE_CODE_GIT_BASH_PATH=%s", _p)
            break


class AgentSDKClient:
    """Claude Agent SDK wrapper, replacing LLMClient.

    Uses claude_agent_sdk.query() for all LLM interactions.
    Authentication is handled automatically by Claude Code CLI.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.total_calls = 0

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_turns: int = 1,
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> str:
        """Send a request and return the text result.

        Args:
            system_prompt: System message guiding the model's behavior.
            user_prompt: User message content.
            model: Model name override. Defaults to writing model.
            max_turns: Maximum agentic turns.
            on_event: Optional callback fired with progress events:
                      {"type": "thinking", "text": str}  — model is reasoning
                      {"type": "text",     "text": str}  — first text chunk
                      {"type": "result"}                 — final result ready

        Returns:
            The model's text response.

        Raises:
            LLMError: If the query fails.
        """
        model = model or self.settings.llm_model_writing
        self.total_calls += 1

        logger.debug("AgentSDK call: model=%s, max_turns=%d", model, max_turns)

        try:
            result_text = ""
            _text_fired = False
            # IMPORTANT: Do NOT return/break early from inside the async for loop.
            # The query() generator uses anyio cancel scopes internally; exiting
            # the loop prematurely causes "Attempted to exit cancel scope in a
            # different task" errors. We must exhaust the generator fully.
            options_kwargs = {
                "system_prompt": system_prompt,
                "model": model,
                "max_turns": max_turns,
            }
            if max_turns and max_turns > 1:
                options_kwargs["permission_mode"] = "bypassPermissions"
                git_bash = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
                if git_bash:
                    # Use Git Bash to avoid WSL popup windows on Windows
                    options_kwargs["env"] = {"CLAUDE_CODE_GIT_BASH_PATH": git_bash}
                elif sys.platform == "win32":
                    # No Git Bash found — disable Bash tool to avoid WSL popups
                    options_kwargs["disallowed_tools"] = ["Bash"]
            async for message in query(
                prompt=user_prompt,
                options=ClaudeAgentOptions(**options_kwargs),
            ):
                if isinstance(message, ResultMessage):
                    result_text = message.result or ""
                    logger.debug(
                        "AgentSDK result: %d chars, cost=$%s",
                        len(result_text),
                        message.total_cost_usd,
                    )
                    if on_event:
                        on_event({"type": "result"})
                elif isinstance(message, AssistantMessage):
                    for block in message.content:
                        block_type = getattr(block, "type", None)
                        if block_type == "thinking":
                            thinking = getattr(block, "thinking", "")
                            if thinking and on_event:
                                on_event({"type": "thinking", "text": thinking})
                        else:
                            text = getattr(block, "text", None)
                            if text:
                                if on_event and not _text_fired:
                                    _text_fired = True
                                    on_event({"type": "text", "text": text})
                                if not result_text:
                                    result_text += text
        except Exception as e:
            raise LLMError(f"Agent SDK query failed: {e}") from e

        if not result_text:
            logger.warning("AgentSDK returned no content")

        return result_text

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_turns: int = 1,
    ) -> dict:
        """Send a request and parse the response as JSON.

        Args:
            system_prompt: System message guiding the model's behavior.
            user_prompt: User message content.
            model: Model name override.
            max_turns: Maximum agentic turns.

        Returns:
            Parsed JSON dict from the response.

        Raises:
            LLMResponseParseError: If response cannot be parsed as JSON.
        """
        text = await self.chat(system_prompt, user_prompt, model, max_turns)
        try:
            return parse_json_response(text)
        except ValueError as e:
            raise LLMResponseParseError(str(e), raw_response=text) from e

    async def chat_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str] = None,
        max_turns: int = 5,
        mcp_servers: Optional[list] = None,
    ) -> str:
        """Agentic call with tools — Claude decides which tools to use.

        Args:
            system_prompt: System message guiding the model's behavior.
            user_prompt: User message content.
            model: Model name override.
            max_turns: Maximum agentic turns for tool use.
            mcp_servers: Optional list of MCP server configs for tool access.

        Returns:
            The final text result after tool interactions.

        Raises:
            LLMError: If the query fails.
        """
        model = model or self.settings.llm_model_writing
        self.total_calls += 1

        logger.debug("AgentSDK tool call: model=%s, max_turns=%d", model, max_turns)

        options_kwargs = {
            "system_prompt": system_prompt,
            "model": model,
            "max_turns": max_turns,
        }
        if mcp_servers:
            options_kwargs["mcp_servers"] = mcp_servers

        try:
            result_text = ""
            # Exhaust the generator fully — see chat() comment about cancel scopes.
            async for message in query(
                prompt=user_prompt,
                options=ClaudeAgentOptions(**options_kwargs),
            ):
                if isinstance(message, ResultMessage):
                    result_text = message.result or ""
                elif isinstance(message, AssistantMessage):
                    if not result_text:
                        parts = []
                        for block in message.content:
                            if hasattr(block, "text"):
                                parts.append(block.text)
                        if parts:
                            result_text = "".join(parts)
        except Exception as e:
            raise LLMError(f"Agent SDK tool query failed: {e}") from e

        return result_text

    def get_usage_summary(self) -> dict:
        """Return call count statistics."""
        return {"total_calls": self.total_calls}
