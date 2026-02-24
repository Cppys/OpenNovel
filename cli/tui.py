"""OpenNovel TUI — Textual-based chat interface.

Layout:
  ┌─ banner (static) ───────────────────────────────┐
  ├─ status bar (static) ───────────────────────────┤
  ├─ chat log (scrollable, fills remaining space) ──┤
  └─ input box (fixed at bottom) ───────────────────┘
"""

import asyncio
import logging

from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, RichLog, Static
from textual import work

logger = logging.getLogger(__name__)


class _TUIConsole:
    """Proxy that redirects console.print() calls to Textual's RichLog.

    Passed to ChatSession so all action/send output appears inside the TUI
    chat area instead of raw terminal output.
    """

    def __init__(self, app: "OpenNovelTUI"):
        self._app = app

    # ── Properties expected by ChatSession / render helpers ──────────────

    class _FakeSize:
        width = 120

    @property
    def size(self):
        return self._FakeSize()

    def input(self, prompt: str = "") -> str:
        raise RuntimeError("TUI mode: use the Input widget, not console.input()")

    # ── Main output method ────────────────────────────────────────────────

    def print(self, *args, style: str = None, end: str = "\n",
              markup: bool = True, **kwargs) -> None:
        if not args:
            content: object = ""
        elif isinstance(args[0], str):
            text = args[0]
            content = f"[{style}]{text}[/{style}]" if style else text
        else:
            # Rich renderable (Markdown, Text, Table, …)
            content = args[0]

        # Schedule write back to Textual's main thread
        self._app.call_from_thread(self._app._log_write, content)

    def _log_write(self, content) -> None:  # pragma: no cover
        """Used only when called from the main thread directly."""
        self._app._log_write(content)


class OpenNovelTUI(App):
    """OpenNovel Textual TUI application."""

    CSS = """
    Screen {
        background: black;
        layers: base;
    }

    #banner {
        height: auto;
        background: #121212;
        border: tall #3a3a3a;
        padding: 1 2;
        content-align: center middle;
    }

    #status {
        height: 1;
        padding: 0 2;
        color: #767676;
        background: transparent;
    }

    #chat_log {
        height: 1fr;
        border: round #4e4e4e;
        padding: 0 1;
        background: transparent;
        scrollbar-gutter: stable;
    }

    #input_box {
        height: 3;
        border: round dodgerblue;
        background: transparent;
        padding: 0 1;
        margin-top: 0;
    }

    Input:focus {
        border: round royalblue;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+l", "clear_chat", "清空"),
        Binding("escape", "quit", "退出"),
    ]

    def __init__(self, session):
        super().__init__()
        self.session = session

    # ── Layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        from cli.chat import _build_banner
        yield Static(_build_banner(), id="banner")
        yield Static(self._status_text(), id="status")
        yield RichLog(id="chat_log", markup=True, highlight=True)
        yield Input(placeholder="与AI对话… (/help 查看命令)", id="input_box")

    def on_mount(self) -> None:
        # Wire up the console proxy so ChatSession output goes to RichLog
        self.session.console = _TUIConsole(self)

        # Suppress verbose SDK logs that would otherwise pollute the terminal
        for name in ("claude_agent_sdk", "claude_agent_sdk._internal",
                     "claude_agent_sdk._internal.transport.subprocess_cli"):
            logging.getLogger(name).setLevel(logging.WARNING)

        # Show welcome hint in chat area
        log = self.query_one("#chat_log", RichLog)
        if self.session.novel:
            n = self.session.novel
            log.write(
                f"[bold]{n.title}[/]  [dim]·[/]  {n.genre}  "
                f"[dim](ID: {n.id})[/]"
            )
        log.write(
            "[dim]直接输入消息，AI 将自动执行操作。"
            "  /help  /clear  /quit[/]"
        )

        self.query_one("#input_box", Input).focus()

    # ── Helpers ───────────────────────────────────────────────────────────

    def _status_text(self) -> str:
        model = self.session.settings.llm_model_writing
        path = (
            f"~/opennovel/{self.session.novel.id}"
            if self.session.novel
            else "~/opennovel"
        )
        return f"[dim]{path}    chat-mode    {model}[/]"

    def _log_write(self, content) -> None:
        """Write to the chat log (must be called from the main Textual thread)."""
        self.query_one("#chat_log", RichLog).write(content)

    # ── Input handling ────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_msg = event.value.strip()
        if not user_msg:
            return

        inp = self.query_one("#input_box", Input)
        log = self.query_one("#chat_log", RichLog)
        inp.value = ""

        # Echo user message in chat area
        log.write(f"[bold bright_blue]你>[/] {user_msg}")

        # Slash commands (synchronous, handle immediately)
        if user_msg.startswith("/"):
            result = self.session.handle_command(user_msg)
            if result is None:
                self.exit()
                return
            log.write(result)
            return

        # AI chat — run send() in a worker thread
        # (send() is async; asyncio.run() creates a new loop for the thread)
        inp.disabled = True
        inp.placeholder = "思考中…"
        self._run_ai(user_msg)

    @work(thread=True)
    def _run_ai(self, user_msg: str) -> None:
        """Worker thread: run the async send() and notify on completion."""
        try:
            asyncio.run(self.session.send(user_msg))
        except Exception as e:
            logger.exception("send() failed")
            self.call_from_thread(
                self._log_write,
                f"[red]AI 回复失败：{e}[/]",
            )
        finally:
            self.call_from_thread(self._on_ai_done)

    def _on_ai_done(self) -> None:
        inp = self.query_one("#input_box", Input)
        inp.disabled = False
        inp.placeholder = "与AI对话… (/help 查看命令)"
        inp.focus()

    # ── Actions ───────────────────────────────────────────────────────────

    def action_quit(self) -> None:
        self.exit()

    def action_clear_chat(self) -> None:
        self.session.history.clear()
        self.query_one("#chat_log", RichLog).clear()
        self._log_write("[dim]对话历史已清空[/]")
