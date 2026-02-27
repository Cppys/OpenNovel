"""OpenNovel TUI — Textual-based chat interface (Claude Code style).

Layout:
  ┌─ status bar (path · model) ────────────────────────┐
  ├─ chat log (scrollable, fills remaining space) ─────┤
  │  · welcome banner + tips                           │
  ├─ node graph (pipeline status, hidden by default) ──┤
  ├─ ai status (✦ inline status) ──────────────────────┤
  └─ ╔═ input (double-border) ═══════════════════════╗ ┘
"""

import asyncio
import logging
import threading

from rich.text import Text
from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, RichLog, Static
from textual import work

logger = logging.getLogger(__name__)


# ── Pixel Art Banner (gradient "> OPENNOVEL") ─────────────────────────────

_LETTER_ART: dict[str, list[str]] = {
    '>': ["█▌   ", "███▌ ", "█████", "███▌ ", "█▌   "],
    'O': [" █████ ", "██   ██", "██   ██", "██   ██", " █████ "],
    'P': ["██████ ", "██   ██", "██████ ", "██     ", "██     "],
    'E': ["███████", "██     ", "█████  ", "██     ", "███████"],
    'N': ["██   ██", "███  ██", "██ █ ██", "██  ███", "██   ██"],
    'V': ["██   ██", "██   ██", " ██ ██ ", "  ███  ", "   █   "],
    'L': ["██     ", "██     ", "██     ", "██     ", "███████"],
}

_BANNER_WORD: list[tuple[str, str]] = [
    ('>', "bright_blue"),
    ('O', "dodger_blue1"),
    ('P', "deep_sky_blue1"),
    ('E', "medium_purple3"),
    ('N', "purple"),
    ('N', "magenta"),
    ('O', "hot_pink"),
    ('V', "bright_red"),
    ('E', "red1"),
    ('L', "red"),
]


def _build_banner() -> Text:
    """Build gradient pixel art banner "> OPENNOVEL"."""
    text = Text()
    for line_idx in range(5):
        text.append("  ")
        for i, (letter, color) in enumerate(_BANNER_WORD):
            text.append(_LETTER_ART[letter][line_idx], style=color)
            if i < len(_BANNER_WORD) - 1:
                text.append(" ")
        if line_idx < 4:
            text.append("\n")
    return text


# ── Status symbol + color pulse (replaces spinner frames) ─────────────────

_STATUS_SYMBOL = "✦"
_PULSE_COLORS = ["#60a5fa", "#93c5fd", "#60a5fa", "#3b82f6"]

# ── Pipeline node graph ───────────────────────────────────────────────────

_PIPELINE_NODES = [
    ("initialize", "初始化"),
    ("plan_novel", "大纲"),
    ("load_chapter_context", "上下文"),
    ("retrieve_memory", "记忆"),
    ("write_chapter", "写作"),
    ("edit_chapter", "编辑"),
    ("review_chapter", "审核"),
    ("save_chapter", "保存"),
    ("update_memory", "记忆更新"),
    ("advance_chapter", "推进"),
]


def _render_node_graph(active_node: str, completed_nodes: set[str] | None = None) -> Text:
    """Render a single-line pipeline node graph.

    Active node: ● + bold blue
    Completed nodes: ● + dim green
    Pending nodes: ○ + dim gray
    """
    if completed_nodes is None:
        completed_nodes = set()

    t = Text()
    for i, (node_id, label) in enumerate(_PIPELINE_NODES):
        if i > 0:
            t.append(" → ", style="#4a5568")

        base_active = active_node.split(":")[0] if active_node else ""

        if node_id == base_active:
            t.append(f"● {label}", style="#60a5fa bold")
        elif node_id in completed_nodes:
            t.append(f"● {label}", style="#4ade80 dim")
        else:
            t.append(f"○ {label}", style="#4a5568")

    return t


# ── TUI Console Proxy ────────────────────────────────────────────────────

class _TUIConsole:
    """Proxy that redirects console.print() calls to Textual's RichLog."""

    def __init__(self, app: "OpenNovelTUI"):
        self._app = app

    class _FakeSize:
        width = 120

    @property
    def size(self):
        return self._FakeSize()

    def input(self, prompt: str = "") -> str:
        raise RuntimeError("TUI mode: use the Input widget, not console.input()")

    def set_live(self, live_obj) -> None:
        pass

    def clear_live(self) -> None:
        pass

    def update_status(self, phase: str) -> None:
        self._app.call_from_thread(self._app._show_ai_status, phase)

    def clear_status(self) -> None:
        self._app.call_from_thread(self._app._hide_ai_status)

    def show_thinking(self, text: str) -> None:
        self._app.call_from_thread(self._app._append_thinking, text)

    def update_node_graph(self, node: str) -> None:
        self._app.call_from_thread(self._app._show_node_graph, node)

    def hide_node_graph(self) -> None:
        self._app.call_from_thread(self._app._hide_node_graph)

    @property
    def cancelled(self) -> bool:
        """Check if the current operation has been cancelled."""
        return self._app._cancel_event.is_set()

    def print(self, *args, style: str = None, end: str = "\n",
              markup: bool = True, **kwargs) -> None:
        if not args:
            content: object = ""
        elif isinstance(args[0], str):
            text = args[0]
            content = f"[{style}]{text}[/{style}]" if style else text
        else:
            content = args[0]
        self._app.call_from_thread(self._app._log_write, content)

    def _log_write(self, content) -> None:
        self._app._log_write(content)


class OpenNovelTUI(App):
    """OpenNovel Textual TUI application."""

    CSS = """
    Screen {
        background: #0d1117;
        layers: base;
    }

    #status {
        height: 1;
        padding: 0 2;
        color: #8b949e;
        background: #161b22;
    }

    #chat_log {
        height: 1fr;
        padding: 1 2;
        background: transparent;
        scrollbar-gutter: stable;
    }

    #node_graph {
        height: 1;
        padding: 0 2;
        color: #8b949e;
        background: transparent;
    }

    #ai_status {
        height: 1;
        padding: 0 2;
        color: #60a5fa;
        background: transparent;
    }

    #input_box {
        height: 3;
        border: double #30363d;
        background: #161b22;
        padding: 0 1;
        margin: 0 1 0 1;
    }

    #input_box:focus {
        border: double #3b82f6;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+l", "clear_chat", "清空"),
        Binding("escape", "interrupt_or_quit", "中断/退出", priority=True),
    ]

    def __init__(self, session):
        super().__init__()
        self.session = session

    # ── Layout ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static(self._status_text(), id="status")
        yield RichLog(id="chat_log", markup=True, highlight=True)
        yield Static("", id="node_graph")
        yield Static("", id="ai_status")
        yield Input(placeholder="描述你想做的事... (/help 查看命令)", id="input_box")

    def on_mount(self) -> None:
        self.session.console = _TUIConsole(self)

        # Pulse state for AI status bar
        self._pulse_idx = 0
        self._pulse_timer = None
        self._ai_phase = ""
        self.query_one("#ai_status", Static).display = False

        # Node graph state
        self._completed_nodes: set[str] = set()
        self._current_node = ""
        self.query_one("#node_graph", Static).display = False

        # Cancel signal for interrupting AI
        self._cancel_event = threading.Event()
        self._ai_running = False
        self._ai_worker = None

        # Suppress verbose SDK logs
        for name in ("claude_agent_sdk", "claude_agent_sdk._internal",
                     "claude_agent_sdk._internal.transport.subprocess_cli"):
            logging.getLogger(name).setLevel(logging.WARNING)

        self._render_welcome()
        self.query_one("#input_box", Input).focus()

    # ── Welcome Screen ────────────────────────────────────────────────────

    def _render_welcome(self) -> None:
        log = self.query_one("#chat_log", RichLog)

        # Banner
        log.write(_build_banner())
        log.write("")

        # Version
        subtitle = Text()
        subtitle.append("  v0.1.0", style="dim")
        subtitle.append("  ·  ", style="dim")
        subtitle.append("AI 网文创作工作流", style="#8b949e")
        log.write(subtitle)
        log.write("")

        # Novel info (if bound)
        if self.session.novel:
            n = self.session.novel
            chapters = self.session.db.get_chapters(n.id)
            total = sum(ch.char_count for ch in chapters) if chapters else 0
            characters = self.session.db.get_characters(n.id)

            info = Text()
            info.append("  ── 当前小说 ", style="dim")
            info.append("─" * 40, style="dim")
            log.write(info)

            title_line = Text()
            title_line.append("  ", style="")
            title_line.append(f"《{n.title}》", style="bold")
            title_line.append(f"  {n.genre}", style="#8b949e")
            title_line.append(f"  ID:{n.id}", style="dim")
            log.write(title_line)

            stats_line = Text()
            stats_line.append("  ", style="")
            stats_line.append(f"{len(chapters)}", style="bold cyan")
            stats_line.append(" 章", style="#8b949e")
            stats_line.append("  ·  ", style="dim")
            stats_line.append(f"{total:,}", style="bold cyan")
            stats_line.append(" 字", style="#8b949e")
            if characters:
                stats_line.append("  ·  ", style="dim")
                stats_line.append(f"{len(characters)}", style="bold cyan")
                stats_line.append(" 角色", style="#8b949e")
            log.write(stats_line)
            log.write("")

        # Tips
        tips_header = Text()
        tips_header.append("  ── 试试说 ", style="dim")
        tips_header.append("─" * 42, style="dim")
        log.write(tips_header)

        tips = [
            ('"帮我写一个玄幻小说"', "创建新小说"),
            ('"写第1-5章"', "批量写作"),
            ('"给我看看第3章"', "阅读章节"),
            ('"修改第2章，加入更多对话"', "编辑内容"),
        ]
        for prompt, desc in tips:
            tip_line = Text()
            tip_line.append("  ", style="")
            tip_line.append(prompt, style="bright_blue")
            tip_line.append(f"  {desc}", style="dim")
            log.write(tip_line)
        log.write("")

        # Shortcuts
        shortcuts = Text()
        shortcuts.append("  ", style="")
        shortcuts.append("ctrl+c", style="bold #8b949e")
        shortcuts.append(" 退出", style="dim")
        shortcuts.append("    ", style="")
        shortcuts.append("ctrl+l", style="bold #8b949e")
        shortcuts.append(" 清屏", style="dim")
        shortcuts.append("    ", style="")
        shortcuts.append("/help", style="bold #8b949e")
        shortcuts.append(" 帮助", style="dim")
        shortcuts.append("    ", style="")
        shortcuts.append("/clear", style="bold #8b949e")
        shortcuts.append(" 清空历史", style="dim")
        log.write(shortcuts)

        # Separator
        log.write("")
        sep = Text()
        sep.append("  " + "─" * 56, style="dim")
        log.write(sep)
        log.write("")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _status_text(self) -> str:
        model = self.session.settings.llm_model_writing
        path = (
            f"~/opennovel/{self.session.novel.id}"
            if self.session.novel
            else "~/opennovel"
        )
        return f" {path}  [dim]·[/]  chat  [dim]·[/]  {model}"

    def _log_write(self, content) -> None:
        self.query_one("#chat_log", RichLog).write(content)

    # ── AI Status Bar (✦ color pulse) ──────────────────────────────────

    def _show_ai_status(self, phase: str) -> None:
        self._ai_phase = phase
        self._pulse_idx = 0
        status = self.query_one("#ai_status", Static)
        color = _PULSE_COLORS[0]
        status.update(Text(f"  {_STATUS_SYMBOL} {phase}...", style=color))
        status.display = True
        if not self._pulse_timer:
            self._pulse_timer = self.set_interval(0.4, self._tick_pulse)

    def _hide_ai_status(self) -> None:
        self._ai_phase = ""
        status = self.query_one("#ai_status", Static)
        status.update("")
        status.display = False
        if self._pulse_timer:
            self._pulse_timer.stop()
            self._pulse_timer = None

    def _tick_pulse(self) -> None:
        if not self._ai_phase:
            return
        self._pulse_idx = (self._pulse_idx + 1) % len(_PULSE_COLORS)
        color = _PULSE_COLORS[self._pulse_idx]
        self.query_one("#ai_status", Static).update(
            Text(f"  {_STATUS_SYMBOL} {self._ai_phase}...", style=color)
        )

    # ── Node Graph ──────────────────────────────────────────────────────

    def _show_node_graph(self, active_node: str) -> None:
        base_node = active_node.split(":")[0]
        if self._current_node and self._current_node != base_node:
            self._completed_nodes.add(self._current_node)
        self._current_node = base_node

        graph_widget = self.query_one("#node_graph", Static)
        graph_widget.update(Text("  ").append_text(
            _render_node_graph(active_node, self._completed_nodes)
        ))
        graph_widget.display = True

    def _hide_node_graph(self) -> None:
        graph_widget = self.query_one("#node_graph", Static)
        graph_widget.update("")
        graph_widget.display = False
        self._completed_nodes.clear()
        self._current_node = ""

    def _append_thinking(self, content: str) -> None:
        log = self.query_one("#chat_log", RichLog)
        lines = content.strip().splitlines()
        t = Text()
        for i, line in enumerate(lines):
            if i > 0:
                t.append("\n")
            t.append("  | ", style="#4a5568")
            t.append(line, style="#6b7280 italic")
        log.write(t)

    # ── Input handling ────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_msg = event.value.strip()
        if not user_msg:
            return

        inp = self.query_one("#input_box", Input)
        log = self.query_one("#chat_log", RichLog)
        inp.value = ""

        echo = Text()
        echo.append("> ", style="bright_blue bold")
        echo.append(user_msg)
        log.write(echo)

        if user_msg.startswith("/"):
            result = self.session.handle_command(user_msg)
            if result is None:
                self.exit()
                return
            log.write(result)
            return

        inp.disabled = True
        inp.placeholder = ""
        self._cancel_event.clear()
        self._ai_running = True
        self._ai_worker = self._run_ai(user_msg)

    @work(thread=True)
    def _run_ai(self, user_msg: str) -> None:
        try:
            asyncio.run(self.session.send(user_msg))
        except Exception as e:
            if self._cancel_event.is_set():
                self.call_from_thread(
                    self._log_write,
                    "[dim]  (已中断)[/]",
                )
            else:
                logger.exception("send() failed")
                self.call_from_thread(
                    self._log_write,
                    f"[red]AI 回复失败：{e}[/]",
                )
        finally:
            self.call_from_thread(self._on_ai_done)

    def _on_ai_done(self) -> None:
        self._ai_running = False
        self._hide_ai_status()
        self._hide_node_graph()
        inp = self.query_one("#input_box", Input)
        inp.disabled = False
        inp.placeholder = "描述你想做的事... (/help 查看命令)"
        inp.focus()

    # ── Actions ───────────────────────────────────────────────────────────

    def action_quit(self) -> None:
        self.exit()

    def action_interrupt_or_quit(self) -> None:
        """ESC: interrupt AI if running, otherwise quit."""
        if self._ai_running:
            self._cancel_event.set()
            if self._ai_worker is not None:
                self._ai_worker.cancel()
            self._log_write("[dim]  (已中断)[/]")
            self._on_ai_done()
        else:
            self.exit()

    def action_clear_chat(self) -> None:
        self.session.history.clear()
        log = self.query_one("#chat_log", RichLog)
        log.clear()
        self._render_welcome()
