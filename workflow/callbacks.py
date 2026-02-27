"""Workflow progress callbacks for monitoring and real-time reporting."""

import logging
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class WorkflowCallback(Protocol):
    """Protocol for workflow progress callbacks.

    Implement this protocol to hook into the workflow execution lifecycle.
    """

    def on_node_exit(self, node: str, state: dict) -> None:
        """Called after a node finishes executing with the current accumulated state."""
        ...

    def on_chapter_complete(self, chapter_num: int, total: int, char_count: int) -> None:
        """Called when a chapter has been saved (chapters_written incremented)."""
        ...

    def on_error(self, node: str, error: str) -> None:
        """Called when an error is detected in the workflow state."""
        ...

    def on_workflow_complete(self, final_state: dict) -> None:
        """Called when the entire workflow finishes."""
        ...


class LoggingCallback:
    """Lightweight callback that logs progress to the standard logger."""

    def on_node_exit(self, node: str, state: dict) -> None:
        logger.debug("← node: %s", node)

    def on_chapter_complete(self, chapter_num: int, total: int, char_count: int) -> None:
        logger.info("Chapter %d/%d complete (%d chars)", chapter_num, total or "?", char_count)

    def on_error(self, node: str, error: str) -> None:
        logger.error("Workflow error in '%s': %s", node, error)

    def on_workflow_complete(self, final_state: dict) -> None:
        logger.info(
            "Workflow complete — chapters_written=%d",
            final_state.get("chapters_written", 0),
        )


class RichProgressCallback:
    """Progress callback that renders a Rich live progress display in the terminal."""

    # Labels for sub-step events (fired on entry, so label = current step)
    _NODE_LABELS: dict[str, str] = {
        "initialize": "初始化",
        "plan_novel": "规划小说大纲",
        "plan_novel:genre_research": "分析类型与读者期待",
        "plan_novel:story_architecture": "构建故事架构与角色",
        "plan_novel:conflict_design": "设计冲突与章节大纲",
        "plan_novel:complete": "大纲生成完成",
        "load_chapter_context": "加载章节大纲",
        "load_chapter_context:generating_outlines": "生成本卷章节大纲",
        "retrieve_memory": "检索记忆上下文",
        "write_chapter": "写作章节草稿",
        "edit_chapter": "编辑与润色",
        "review_chapter": "质量审核",
        "save_chapter": "保存章节",
        "update_memory": "更新记忆库",
        "global_review": "全局一致性审核",
        "advance_chapter": "推进章节",
        "handle_error": "处理错误",
    }

    # When a node exits, show the label of the step that is *entering* next.
    # (astream fires events after each node completes, so we display the next step.)
    _ENTERING_LABEL: dict[str, str] = {
        "plan_novel": "加载章节大纲",
        "load_chapter_context": "检索记忆上下文",
        "retrieve_memory": "写作章节草稿",
        "write_chapter": "编辑与润色",
        "edit_chapter": "质量审核",
        "review_chapter": "保存章节",
        "save_chapter": "更新记忆库",
        "update_memory": "推进章节",
        "advance_chapter": "加载章节大纲",
        "global_review": "推进章节",
    }

    def __init__(self, console=None, total_chapters: int = 0):
        """
        Args:
            console: Rich Console instance. Creates one if not provided.
            total_chapters: Total chapters to write (for progress bar max).
        """
        self._console = console
        self._total = total_chapters
        self._progress = None
        self._chapter_task_id = None
        self._node_task_id = None

    def start(self):
        """Start the progress display. Call before running the workflow."""
        from rich.console import Console
        from rich.progress import (
            Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn,
        )

        console = self._console
        if console is None:
            from rich.console import Console
            console = Console()

        self._progress = Progress(
            SpinnerColumn("dots"),
            TextColumn("[progress.description]{task.description}"),
            TaskProgressColumn(),
            console=console,
        )
        self._progress.start()

        self._chapter_task_id = self._progress.add_task(
            "等待开始...",
            total=self._total if self._total > 0 else None,
        )
        self._node_task_id = self._progress.add_task(
            "[dim]初始化中...[/]",
            total=None,
        )

    def stop(self):
        """Stop the progress display."""
        if self._progress:
            self._progress.stop()
            self._progress = None

    def on_node_exit(self, node: str, state: dict) -> None:
        if not self._progress:
            return

        ch = state.get("current_chapter", "")
        ch_suffix = f" (第{ch}章)" if ch else ""

        if ":" in node:
            # Sub-step events (e.g. plan_novel:genre_research) fire on entry,
            # so display their own label.
            label = self._NODE_LABELS.get(node, node)
        elif node == "initialize":
            # Conditional: next step depends on mode
            mode = state.get("mode", "continue")
            label = "规划小说大纲" if mode in ("new", "plan_only") else "加载章节大纲"
        else:
            # Regular node exit: display what is *entering* next
            label = self._ENTERING_LABEL.get(node, self._NODE_LABELS.get(node, node))

        self._progress.update(
            self._node_task_id,
            description=f"[dim]{label}{ch_suffix}[/]",
        )

        # Update chapter progress line to show current chapter being worked on
        if ch and node in ("initialize", "advance_chapter"):
            self._progress.update(
                self._chapter_task_id,
                description=f"正在写第{ch}章...",
            )

    def on_chapter_complete(self, chapter_num: int, total: int, char_count: int) -> None:
        if not self._progress:
            return
        total_label = str(total) if total > 0 else "?"
        self._progress.update(
            self._chapter_task_id,
            completed=chapter_num,
            description=f"[green]已完成 {chapter_num}/{total_label} 章[/] "
                        f"([cyan]{char_count:,}[/]字)",
        )

    def on_error(self, node: str, error: str) -> None:
        if not self._progress:
            return
        self._progress.update(
            self._node_task_id,
            description=f"[red]错误 ({node}): {error[:80]}[/]",
        )

    def on_workflow_complete(self, final_state: dict) -> None:
        if not self._progress:
            return
        written = final_state.get("chapters_written", 0)
        self._progress.update(
            self._chapter_task_id,
            description=f"[bold green]完成！共 {written} 章[/]",
        )
        self._progress.update(self._node_task_id, description="")


class ChatProgressCallback:
    """将工作流进度内联输出到聊天界面（不使用 Rich Progress 组件）。

    Also updates TUI status bar + node graph when running in TUI mode.
    """

    _NODE_LABELS: dict[str, str] = {
        "initialize": "初始化",
        "plan_novel": "规划小说大纲",
        "plan_novel:genre_research": "分析类型与读者期待",
        "plan_novel:story_architecture": "构建故事架构与角色",
        "plan_novel:conflict_design": "设计冲突与章节大纲",
        "plan_novel:complete": "大纲生成完成",
        "load_chapter_context": "加载章节大纲",
        "load_chapter_context:generating_outlines": "生成本卷章节大纲",
        "retrieve_memory": "检索记忆上下文",
        "write_chapter": "写作章节草稿",
        "edit_chapter": "编辑与润色",
        "review_chapter": "质量审核",
        "save_chapter": "保存章节",
        "update_memory": "更新记忆库",
        "global_review": "全局一致性审核",
        "advance_chapter": "推进章节",
        "handle_error": "处理错误",
    }

    # When a node exits, show the label of the step that is *entering* next.
    _ENTERING_LABEL: dict[str, str] = {
        "plan_novel": "加载章节大纲",
        "load_chapter_context": "检索记忆上下文",
        "retrieve_memory": "写作章节草稿",
        "write_chapter": "编辑与润色",
        "edit_chapter": "质量审核",
        "review_chapter": "保存章节",
        "save_chapter": "更新记忆库",
        "update_memory": "推进章节",
        "advance_chapter": "加载章节大纲",
        "global_review": "推进章节",
    }

    def __init__(self, console=None):
        self._console = console

    def _print(self, text: str) -> None:
        if self._console:
            self._console.print(text)

    def _update_status(self, label: str) -> None:
        """Update TUI status bar if console supports it."""
        if self._console and hasattr(self._console, "update_status"):
            self._console.update_status(label)

    def _update_node_graph(self, node: str) -> None:
        """Update TUI node graph if console supports it."""
        if self._console and hasattr(self._console, "update_node_graph"):
            self._console.update_node_graph(node)

    def on_node_exit(self, node: str, state: dict) -> None:
        label = self._NODE_LABELS.get(node, node)

        # Sub-step events get printed inline
        if ":" in node:
            self._print(f"  [dim]--[/] [green]{label}[/]")
            self._update_status(label)
            self._update_node_graph(node)
        else:
            # Regular node: show what is entering next
            entering_label = self._ENTERING_LABEL.get(node, label)
            self._update_status(entering_label)
            self._update_node_graph(node)

    def on_chapter_complete(self, chapter_num: int, total: int, char_count: int) -> None:
        self._print(f"  [dim]--[/] [green]第{chapter_num}章[/] [dim]({char_count:,}字)[/]")

    def on_error(self, node: str, error: str) -> None:
        self._print(f"  [dim]--[/] [red]错误 ({node}): {error}[/]")

    def on_workflow_complete(self, final_state: dict) -> None:
        written = final_state.get("chapters_written", 0)
        novel_id = final_state.get("novel_id", 0)
        title = final_state.get("outline_data", {}).get("title", "")
        if written > 0:
            self._print(f"  [bold green]写作完成 -- 共 {written} 章[/]")
        elif title:
            self._print(f"  [bold green]大纲生成完成 --[/] {title} [dim](ID: {novel_id})[/]")
        else:
            self._print(f"  [bold green]工作流执行完成[/] [dim](小说ID: {novel_id})[/]")

        # Hide node graph when workflow is done
        if self._console and hasattr(self._console, "hide_node_graph"):
            self._console.hide_node_graph()
        if self._console and hasattr(self._console, "clear_status"):
            self._console.clear_status()
