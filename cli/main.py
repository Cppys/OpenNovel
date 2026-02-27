"""CLI entry point — OpenNovel AI 写作系统。

用法：
  opennovel              进入 AI 对话模式（默认）
  opennovel -n 1         绑定小说 ID 进入对话
  opennovel new ...      直接创建小说大纲
  opennovel write ...    直接写章节
  opennovel --help       查看所有命令
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows to avoid GBK encoding errors with Rich
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import click
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn
from rich.table import Table

from cli.theme import (
    get_console,
    app_header,
    command_panel,
    success_panel,
    novel_summary_panel,
    volume_tree,
    character_cards,
    outline_tree_from_db,
)
from config.settings import Settings
from config.logging_config import setup_logging
from models.database import Database
from models.enums import NovelStatus, ChapterStatus
from workflow.callbacks import RichProgressCallback

console = get_console()


def _init_logging(verbose: bool):
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    settings = Settings()
    setup_logging(level=level, log_dir=settings.log_dir)


@click.group(invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--novel-id", "-n", default=None, type=int, help="绑定小说ID（对话模式）")
@click.pass_context
def cli(ctx, verbose, novel_id):
    """OpenNovel — AI 驱动的中文网文创作系统

    \b
    直接运行 opennovel 进入 AI 对话模式：
      opennovel          通用助手模式
      opennovel -n 1     绑定小说 ID 进入对话

    \b
    或使用子命令直接控制：
      opennovel new -g 玄幻 -p "少年获得传承"
      opennovel write -n 1 -c 1-10
      opennovel status
    """
    _init_logging(verbose)
    if ctx.invoked_subcommand is None:
        # 没有子命令 → 进入 TUI 对话模式
        from cli.chat import ChatSession
        from cli.tui import OpenNovelTUI

        settings = Settings()
        db = Database(settings.sqlite_db_path)

        novel = None
        if novel_id:
            novel = db.get_novel(novel_id)
            if not novel:
                console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
                sys.exit(1)

        session = ChatSession(db=db, novel=novel, settings=settings)
        app = OpenNovelTUI(session)
        app.run()


# ---------------------------------------------------------------------------
# new command
# ---------------------------------------------------------------------------

# Planning step labels for progress display
_PLAN_STEPS = {
    "genre_research": "分析类型与读者期待",
    "story_architecture": "构建故事架构与角色",
    "conflict_design": "设计冲突与章节大纲",
    "complete": "大纲生成完成",
}


@cli.command()
@click.option("--genre", "-g", required=True, help="小说类型（如：玄幻、都市、言情、悬疑）")
@click.option("--premise", "-p", required=True, help="故事核心设定/创意")
@click.option("--chapters", "-c", default=30, help="规划的章节大纲数量（默认30）")
@click.option("--chapters-per-volume", "-v", default=30, help="每卷章节数（默认30）")
@click.option("--ideas", "-i", default="", help="补充想法/创意备注（可选），如特定情节、角色安排、结局方向等")
def new(genre, premise, chapters, chapters_per_volume, ideas):
    """创建新小说并生成故事大纲（仅规划，不写章节）。

    示例：
      opennovel new -g 玄幻 -p "少年偶获上古传承，踏上逆天之路"
      opennovel new -g 豪门总裁 -p "豪门替嫁" -c 1200 -v 30
    """
    from workflow.graph import run_workflow
    import math

    num_volumes = math.ceil(chapters / chapters_per_volume)

    console.print(app_header())
    console.print()

    fields = {
        "类型": genre,
        "设定": premise,
        "规划": f"{chapters} 章",
        "每卷": f"{chapters_per_volume} 章 ({num_volumes} 卷)",
    }
    if ideas:
        fields["想法"] = ideas
    console.print(command_panel("创建新小说", fields))
    console.print()

    # Planning progress display with 3-step progress bar
    progress = Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    )
    plan_task_id = None
    current_step = [0]  # mutable for closure

    class PlanningCallback:
        """Minimal callback that updates the planning progress bar."""

        def on_node_exit(self, node: str, state: dict) -> None:
            # Handle plan_novel:substep events
            if node.startswith("plan_novel:"):
                step = node.split(":", 1)[1]
                label = _PLAN_STEPS.get(step, step)
                if plan_task_id is not None:
                    if step == "complete":
                        # All 3 steps done
                        progress.update(
                            plan_task_id,
                            completed=3,
                            description=f"  [success]{label}[/]",
                        )
                    else:
                        # Mark previous step as done, show current step as in-progress
                        progress.update(
                            plan_task_id,
                            completed=current_step[0],
                            description=f"  {label}...",
                        )
                        current_step[0] += 1

        def on_chapter_complete(self, chapter_num: int, total: int, char_count: int) -> None:
            pass

        def on_error(self, node: str, error: str) -> None:
            if plan_task_id is not None:
                progress.update(plan_task_id, description=f"  [error]错误: {error[:60]}[/]")

        def on_workflow_complete(self, final_state: dict) -> None:
            if plan_task_id is not None:
                progress.update(plan_task_id, completed=3, description="  [success]大纲生成完成[/]")

    try:
        cb = PlanningCallback()
        progress.start()
        plan_task_id = progress.add_task("  准备中...", total=3)

        try:
            final_state = asyncio.run(run_workflow(
                mode="plan_only",
                genre=genre,
                premise=premise,
                ideas=ideas,
                target_chapters=chapters,
                chapters_per_volume=chapters_per_volume,
                callback=cb,
            ))
        finally:
            progress.stop()

        console.print()

        error = final_state.get("error", "")
        if error:
            console.print(f"\n[error]错误：{error}[/]")
            sys.exit(1)

        novel_id = final_state.get("novel_id", 0)

        # Load accurate info from DB
        settings = Settings()
        db = Database(settings.sqlite_db_path)
        novel = db.get_novel(novel_id)
        characters = db.get_characters(novel_id)
        outlines = db.get_outlines(novel_id)

        # Result header
        console.print(app_header("大纲生成完成"))
        console.print()

        # Novel summary panel
        if novel:
            console.print(novel_summary_panel(novel, characters, outlines))
            console.print()

        # Volume/chapter tree from outline_data
        outline_data = final_state.get("outline_data", {})
        vol_data = outline_data.get("volumes", [])
        if vol_data:
            console.print(volume_tree(vol_data))
            console.print()

        # Character cards
        if characters:
            console.print("[bold]主要角色[/]")
            console.print(character_cards(characters))
            console.print()

        console.print(f"下一步: [info]opennovel write -n {novel_id} -c 1-{len(outlines)}[/]")

    except KeyboardInterrupt:
        console.print("\n[warning]已中断[/]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[error]运行失败：{e}[/]")
        logging.getLogger(__name__).exception("Workflow failed")
        sys.exit(1)


# ---------------------------------------------------------------------------
# write command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
@click.option("--chapters", "-c", required=True, type=str,
              help="章节选择：30=写第30章，1-30=写第1到30章，1,5,10=写指定章")
def write(novel_id, chapters):
    """为已规划的小说写章节（保存到本地，不上传番茄）。

    示例：
      opennovel write -n 4 -c 1          # 写第1章
      opennovel write -n 4 -c 1-10       # 写第1到10章
      opennovel write -n 4 -c 1,5,10     # 写第1、5、10章
    """
    from workflow.graph import run_workflow

    settings = Settings()
    db = Database(settings.sqlite_db_path)
    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    chapter_list = _parse_chapter_numbers(chapters)
    last_ch = db.get_last_chapter_number(novel_id)

    console.print(app_header())
    console.print()
    console.print(command_panel("写作章节", {
        "小说": f"{novel.title}（{novel.genre}）",
        "已有章节": str(last_ch),
        "写作": _format_chapter_list(chapter_list),
    }))
    console.print()

    try:
        cb = RichProgressCallback(console=console, total_chapters=len(chapter_list))
        cb.start()
        try:
            final_state = asyncio.run(run_workflow(
                mode="continue",
                novel_id=novel_id,
                genre=novel.genre,
                chapter_list=chapter_list,
                callback=cb,
            ))
        finally:
            cb.stop()

        written = final_state.get("chapters_written", 0)
        error = final_state.get("error", "")

        if error:
            console.print(f"\n[error]错误：{error}[/]")
            sys.exit(1)

        all_chapters = db.get_chapters(novel_id)
        total_chars = sum(ch.char_count for ch in all_chapters)

        # Compute average score for newly written chapters
        written_nums = set(chapter_list)
        new_chapters = [ch for ch in all_chapters if ch.chapter_number in written_nums]
        scores = [ch.review_score for ch in new_chapters if ch.review_score]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        console.print()
        console.print(success_panel("写作完成", (
            f"  新增: [stat.value]{written}[/] 章\n"
            f"  总字数: [stat.value]{total_chars:,}[/]\n"
            f"  平均评分: [stat.value]{avg_score:.1f}[/]"
        )))
        console.print(f"\n下一步: [info]opennovel publish -n {novel_id}[/]")
        _print_usage_summary(final_state)

    except KeyboardInterrupt:
        console.print("\n[warning]已中断[/]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[error]写作失败：{e}[/]")
        logging.getLogger(__name__).exception("Write failed")
        sys.exit(1)


# ---------------------------------------------------------------------------
# continue command
# ---------------------------------------------------------------------------

@cli.command(name="continue")
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
@click.option("--chapters", "-c", required=True, type=str,
              help="章节选择：30=写第30章，1-30=写第1到30章，1,5,10=写指定章")
def continue_novel(novel_id, chapters):
    """续写已有小说（write 命令的别名）。

    示例：
      opennovel continue -n 1 -c 1-5
    """
    from workflow.graph import run_workflow

    settings = Settings()
    db = Database(settings.sqlite_db_path)
    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    chapter_list = _parse_chapter_numbers(chapters)
    last_ch = db.get_last_chapter_number(novel_id)

    console.print(app_header())
    console.print()
    console.print(command_panel("续写小说", {
        "小说": f"{novel.title}（{novel.genre}）",
        "已有章节": str(last_ch),
        "续写": _format_chapter_list(chapter_list),
    }))
    console.print()

    try:
        cb = RichProgressCallback(console=console, total_chapters=len(chapter_list))
        cb.start()
        try:
            final_state = asyncio.run(run_workflow(
                mode="continue",
                novel_id=novel_id,
                genre=novel.genre,
                chapter_list=chapter_list,
                callback=cb,
            ))
        finally:
            cb.stop()

        written = final_state.get("chapters_written", 0)
        error = final_state.get("error", "")

        if error:
            console.print(f"\n[error]错误：{error}[/]")
            sys.exit(1)

        all_chapters = db.get_chapters(novel_id)
        total_chars = sum(ch.char_count for ch in all_chapters)

        console.print()
        console.print(success_panel("续写完成", (
            f"  新增: [stat.value]{written}[/] 章\n"
            f"  总字数: [stat.value]{total_chars:,}[/]"
        )))
        _print_usage_summary(final_state)

    except KeyboardInterrupt:
        console.print("\n[warning]已中断[/]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[error]续写失败：{e}[/]")
        sys.exit(1)


# ---------------------------------------------------------------------------
# publish command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
@click.option("--chapters", "-c", default="all",
              help="要上传的章节（all=全部待上传、1-10=范围、1,2,3=指定章号）")
@click.option("--mode", "-m", default="publish", type=click.Choice(["draft", "publish"]),
              help="上传模式：draft=仅保存草稿、publish=直接发布（默认）")
def publish(novel_id, chapters, mode):
    """将已审核的章节上传到番茄小说（首次自动建书）。

    示例：
      opennovel publish -n 1
      opennovel publish -n 1 -c 1-10
      opennovel publish -n 1 -c 1,2,3
    """
    from agents.publisher_agent import PublisherAgent

    settings = Settings()
    db = Database(settings.sqlite_db_path)

    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    console.print(app_header())
    console.print()

    # Show already-published chapters as context
    published_chapters = db.get_chapters(novel_id, ChapterStatus.PUBLISHED)
    if published_chapters:
        console.print(
            f"[muted]已上传章节: {len(published_chapters)} 章"
            f"（第{published_chapters[0].chapter_number}-"
            f"{published_chapters[-1].chapter_number}章）[/]"
        )

    # Only upload reviewed (not yet published) chapters
    reviewed_chapters = db.get_chapters(novel_id, ChapterStatus.REVIEWED)
    if not reviewed_chapters:
        if published_chapters:
            console.print(f"[warning]没有新的待上传章节（已有 {len(published_chapters)} 章已上传）[/]")
        else:
            console.print("[error]没有可上传的已审核章节，请先使用 write 命令写章节[/]")
        sys.exit(0)

    # Parse chapter selection from reviewed chapters
    to_publish = _parse_chapter_selection(chapters, reviewed_chapters)

    if not to_publish:
        console.print("[warning]所选范围内没有待上传的已审核章节[/]")
        sys.exit(0)

    # Show chapters to upload
    ch_table = Table(title="待上传章节", show_header=True, border_style="dim")
    ch_table.add_column("章号", style="chapter.num")
    ch_table.add_column("标题")
    ch_table.add_column("字数", justify="right")
    for ch in to_publish:
        ch_table.add_row(str(ch.chapter_number), ch.title or "-", str(ch.char_count))
    console.print(ch_table)

    # Check fanqie_book_id — fetch book list and let user bind
    if not novel.fanqie_book_id:
        console.print(
            f"\n[warning]该小说尚未绑定番茄书ID。[/]\n"
            f"[info]请先在 fanqienovel.com 作家后台手动建书，然后在此处选择绑定。[/]"
        )

        existing_books: list[dict] = []
        try:
            console.print("[info]正在获取番茄书籍列表...[/]")
            publisher_list = PublisherAgent(settings=settings)
            existing_books = publisher_list.get_book_list_sync()
        except Exception as e:
            logger.debug("get_book_list failed: %s", e)

        book_id = ""
        if existing_books:
            import questionary
            _MANUAL = "__manual__"
            choices = [
                questionary.Choice(
                    title=f"{b.get('book_name', '未命名')}  (book_id: {b.get('book_id', '?')})",
                    value=str(b.get("book_id", "")),
                )
                for b in existing_books
                if b.get("book_id")
            ]
            choices.append(questionary.Choice(title="手动输入 book_id…", value=_MANUAL))

            selected = questionary.select(
                "请选择要绑定的番茄书籍（↑↓ 移动，回车确认）：",
                choices=choices,
            ).ask()  # returns None if Ctrl+C

            if selected is None or selected == "":
                console.print("[warning]已取消[/]")
                sys.exit(0)
            elif selected == _MANUAL:
                book_id = click.prompt("请输入 book_id（回车取消）", default="").strip()
            else:
                book_id = selected
        else:
            console.print("[warning]未获取到书籍列表，请前往番茄作家后台查看 book_id[/]")
            book_id = click.prompt("请输入 book_id（回车取消）", default="").strip()

        if not book_id:
            console.print("[warning]已取消，请在番茄后台建书后重试[/]")
            sys.exit(0)

        novel.fanqie_book_id = book_id
        db.update_novel(novel)
        console.print(f"[success]番茄书ID 已绑定：{book_id}[/]")

    console.print()
    console.print(command_panel("上传到番茄小说", {
        "小说": novel.title,
        "番茄书ID": novel.fanqie_book_id,
        "待上传": f"{len(to_publish)} 章",
        "模式": "直接发布" if mode == "publish" else "仅保存草稿",
    }))
    console.print()

    # Prepare and run publish
    chapter_data = [
        {
            "chapter_number": ch.chapter_number,
            "title": ch.title,
            "content": ch.content or "",
        }
        for ch in to_publish
    ]

    publisher = PublisherAgent(settings=settings)

    # Upload with progress
    results = publisher.publish_sync(
        book_id=novel.fanqie_book_id,
        chapters=chapter_data,
        publish_mode=mode,
    )

    # Show results table and update DB status
    result_table = Table(title="上传结果", show_header=True, border_style="dim")
    result_table.add_column("章号", style="chapter.num")
    result_table.add_column("标题")
    result_table.add_column("结果")

    success_count = 0
    for ch, result in zip(to_publish, results):
        if result.get("success"):
            success_count += 1
            ch.status = ChapterStatus.PUBLISHED
            ch.fanqie_chapter_id = result.get("item_id", "")
            db.update_chapter(ch)
            result_table.add_row(
                str(ch.chapter_number),
                ch.title or "-",
                "[success]已发布[/]" if mode == "publish" else "[success]草稿已保存[/]",
            )
        else:
            result_table.add_row(
                str(ch.chapter_number),
                ch.title or "-",
                f"[error]{result.get('message', '失败')}[/]",
            )

    console.print(result_table)
    console.print()

    if success_count == len(to_publish):
        console.print(success_panel(
            "上传完成",
            f"  成功上传 [stat.value]{success_count}[/] 章",
        ))
    else:
        console.print(Panel(
            f"  成功: [success]{success_count}[/]  失败: [error]{len(to_publish) - success_count}[/]",
            title="[warning]上传部分完成[/]",
            border_style="yellow",
            padding=(0, 2),
        ))


def _parse_chapter_numbers(arg: str) -> list[int]:
    """Parse chapter selection argument into a list of chapter numbers.

    Supported formats:
      "30"      -> [30]           (single chapter)
      "1-30"    -> [1, 2, ..., 30] (range)
      "1,5,10"  -> [1, 5, 10]     (comma-separated)
    """
    arg = arg.strip()
    try:
        # Range: e.g. "1-30"
        if "-" in arg and "," not in arg:
            parts = arg.split("-", 1)
            start, end = int(parts[0]), int(parts[1])
            if start > end:
                console.print(f"[error]无效范围: {arg}（起始章号不能大于结束章号）[/]")
                sys.exit(1)
            return list(range(start, end + 1))

        # Comma-separated: e.g. "1,5,10"
        if "," in arg:
            nums = sorted(set(int(x.strip()) for x in arg.split(",")))
            return nums

        # Single number
        return [int(arg)]

    except (ValueError, IndexError):
        console.print(
            f"[error]无效的章节格式: {arg}（支持：30、1-30、1,5,10）[/]"
        )
        sys.exit(1)


def _format_chapter_list(chapter_list: list[int]) -> str:
    """Format a chapter list for display."""
    if len(chapter_list) == 1:
        return f"第{chapter_list[0]}章"
    if len(chapter_list) <= 5:
        return "第" + ",".join(str(n) for n in chapter_list) + "章"
    return f"第{chapter_list[0]}-{chapter_list[-1]}章（共{len(chapter_list)}章）"


def _parse_chapter_selection(chapters_arg: str, available_chapters: list) -> list:
    """Parse chapter selection argument and return matching chapters.

    Supported formats:
      all       -> all available chapters
      1-10      -> chapters 1 through 10 (inclusive)
      1,2,3     -> chapters 1, 2, and 3
      5         -> single chapter 5
    """
    if chapters_arg == "all":
        return available_chapters

    available_map = {ch.chapter_number: ch for ch in available_chapters}

    try:
        # Range: e.g. "1-10"
        if "-" in chapters_arg and "," not in chapters_arg:
            parts = chapters_arg.split("-", 1)
            start, end = int(parts[0]), int(parts[1])
            return [available_map[n] for n in range(start, end + 1) if n in available_map]

        # Comma-separated: e.g. "1,2,3"
        if "," in chapters_arg:
            nums = [int(x.strip()) for x in chapters_arg.split(",")]
            return [available_map[n] for n in nums if n in available_map]

        # Single number
        n = int(chapters_arg)
        return [available_map[n]] if n in available_map else []

    except (ValueError, IndexError):
        console.print(
            f"[error]无效的章节格式: {chapters_arg}（支持：all、1-10、1,2,3、单个章号）[/]"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--novel-id", "-n", default=None, type=int, help="查看指定小说（不指定则列出所有）")
def status(novel_id):
    """查看小说状态和进度。

    示例：
      opennovel status
      opennovel status -n 1
    """
    settings = Settings()
    db = Database(settings.sqlite_db_path)

    console.print(app_header())
    console.print()

    if novel_id:
        novel = db.get_novel(novel_id)
        if not novel:
            console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
            sys.exit(1)

        _show_novel_detail(db, novel)
    else:
        novels = db.list_novels()
        if not novels:
            console.print("[warning]暂无小说记录。使用 [info]opennovel new[/] 创建新小说。[/]")
            return
        _show_novel_list(novels)


def _show_novel_list(novels):
    """Display a table of all novels."""
    table = Table(title="小说列表", show_lines=True, border_style="dim")
    table.add_column("ID", style="chapter.num")
    table.add_column("标题", style="bold")
    table.add_column("类型", style="genre")
    table.add_column("状态")
    table.add_column("目标章数", justify="right")

    for n in novels:
        status_color = {
            NovelStatus.PLANNING: "yellow",
            NovelStatus.WRITING: "green",
            NovelStatus.PAUSED: "dim",
            NovelStatus.COMPLETED: "cyan",
        }.get(n.status, "white")

        table.add_row(
            str(n.id),
            n.title,
            n.genre,
            f"[{status_color}]{n.status.value}[/]",
            str(n.target_chapter_count or "无限"),
        )

    console.print(table)


def _show_novel_detail(db: Database, novel):
    """Display detailed info about a single novel."""
    chapters = db.get_chapters(novel.id)
    characters = db.get_characters(novel.id)
    outlines = db.get_outlines(novel.id)
    volumes = db.get_volumes(novel.id) if hasattr(db, "get_volumes") else []

    # Novel summary
    synopsis = novel.synopsis or ""
    if len(synopsis) > 200:
        synopsis = synopsis[:200] + "..."

    total_chars = sum(ch.char_count for ch in chapters) if chapters else 0

    console.print(Panel(
        f"  [stat.label]类型:[/] [genre]{novel.genre}[/]  "
        f"[muted]|[/]  [stat.label]状态:[/] {novel.status.value}  "
        f"[muted]|[/]  [stat.label]目标:[/] [stat.value]{novel.target_chapter_count or '无限'}[/] 章\n"
        f"  [stat.label]章节:[/] [stat.value]{len(chapters)}[/]  "
        f"[muted]|[/]  [stat.label]角色:[/] [stat.value]{len(characters)}[/]  "
        f"[muted]|[/]  [stat.label]总字数:[/] [stat.value]{total_chars:,}[/]\n"
        f"  [stat.label]简介:[/] {synopsis}",
        title=f"[bold]{novel.title}[/] [muted](ID: {novel.id})[/]",
        border_style="dim",
        padding=(0, 2),
    ))
    console.print()

    # Volume/chapter tree
    if outlines:
        console.print(outline_tree_from_db(outlines, volumes))
        console.print()

    # Chapter table
    if chapters:
        ch_table = Table(title="章节列表", border_style="dim")
        ch_table.add_column("章号", style="chapter.num")
        ch_table.add_column("标题")
        ch_table.add_column("字数", justify="right")
        ch_table.add_column("状态")
        ch_table.add_column("评分", justify="right")

        for ch in chapters:
            status_color = {
                ChapterStatus.PLANNED: "dim",
                ChapterStatus.DRAFTED: "yellow",
                ChapterStatus.EDITED: "blue",
                ChapterStatus.REVIEWED: "green",
                ChapterStatus.PUBLISHED: "cyan",
            }.get(ch.status, "white")

            score_str = f"{ch.review_score:.1f}" if ch.review_score else "-"
            ch_table.add_row(
                str(ch.chapter_number),
                ch.title or "-",
                str(ch.char_count),
                f"[{status_color}]{ch.status.value}[/]",
                score_str,
            )

        console.print(ch_table)
        console.print()

    # Character cards
    if characters:
        console.print("[bold]主要角色[/]")
        console.print(character_cards(characters))


# ---------------------------------------------------------------------------
# characters command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
def characters(novel_id):
    """查看小说角色列表。

    示例：
      opennovel characters -n 1
    """
    settings = Settings()
    db = Database(settings.sqlite_db_path)

    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    chars = db.get_characters(novel_id)

    console.print(app_header())
    console.print()
    console.print(
        f"[bold]《{novel.title}》角色列表[/]  [muted](共 {len(chars)} 个)[/]"
    )
    console.print()

    if not chars:
        console.print("[warning]暂无角色记录[/]")
        return

    console.print(character_cards(chars))


# ---------------------------------------------------------------------------
# setup-browser command
# ---------------------------------------------------------------------------

@cli.command(name="setup-browser")
def setup_browser():
    """首次登录番茄小说作家后台（扫码登录）。"""
    import asyncio
    from agents.publisher_agent import PublisherAgent

    console.print(app_header())
    console.print()
    console.print("[bold]正在启动浏览器...[/]")

    async def _setup():
        publisher = PublisherAgent()
        try:
            await publisher.launch_browser(headless=False)  # must show window for QR login
            console.print("浏览器已启动，正在检查登录状态...")
            logged_in = await publisher.ensure_logged_in()
            if logged_in:
                settings = Settings()
                console.print(f"[success]登录成功！认证状态已保存至 {settings.auth_state_path}[/]")
                console.print("[success]后续执行 publish 命令无需重新登录。[/]")
            else:
                console.print("[error]登录失败或超时，请重试。[/]")
        finally:
            await publisher.close()

    asyncio.run(_setup())


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--novel-id", "-n", required=True, type=int, help="要删除的小说ID")
@click.option("--volume", "-v", type=int, default=None, help="删除指定卷号（保留小说其他数据）")
@click.option("--chapter", "-c", type=str, default=None, help="删除指定章节，如 '3' 或 '5-10'")
@click.option("--force", "-f", is_flag=True, help="跳过确认直接删除")
def delete(novel_id, volume, chapter, force):
    """删除小说、卷或章节数据。

    示例：
      opennovel delete -n 3              # 删除整部小说
      opennovel delete -n 3 -v 2         # 删除第2卷及其章节
      opennovel delete -n 3 -c 5-10      # 删除第5-10章
      opennovel delete -n 3 -c 3         # 删除第3章
      opennovel delete -n 3 -v 1 -f      # 跳过确认
    """
    settings = Settings()
    db = Database(settings.sqlite_db_path)

    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    console.print(app_header())
    console.print()

    # ── Delete specific chapters ──
    if chapter is not None:
        from cli.chat import _parse_chapter_range
        chapter_list = _parse_chapter_range(chapter)
        if not chapter_list:
            console.print(f"[error]无效的章节范围: '{chapter}'[/]")
            sys.exit(1)

        console.print(Panel(
            f"  [stat.label]小说:[/] [bold]{novel.title}[/] [muted](ID: {novel_id})[/]\n"
            f"\n"
            f"  [error]将删除以下章节:[/]\n"
            f"    第{chapter_list[0]}-{chapter_list[-1]}章"
            f"（共{len(chapter_list)}章）",
            title="[error]删除章节[/]",
            border_style="red",
            padding=(0, 2),
        ))

        if not force:
            confirmed = click.confirm("确认删除？此操作不可撤销", default=False)
            if not confirmed:
                console.print("[warning]已取消[/]")
                return

        deleted = db.delete_chapters(novel_id, chapter_list)

        try:
            from memory.chroma_store import ChromaStore
            chroma = ChromaStore(settings.chroma_persist_dir)
            chroma.delete_chapter_data(novel_id, chapter_list)
        except Exception as e:
            console.print(f"[warning]向量记忆清除失败（不影响主数据）: {e}[/]")

        console.print(f"\n[success]已删除 {deleted} 章[/]")
        return

    # ── Delete specific volume ──
    if volume is not None:
        volumes = db.get_volumes(novel_id)
        vol_obj = next((v for v in volumes if v.volume_number == volume), None)
        if not vol_obj:
            console.print(f"[error]未找到第{volume}卷[/]")
            sys.exit(1)

        # Find chapters in this volume
        all_chapters = db.get_chapters(novel_id)
        vol_chapters = [ch for ch in all_chapters if ch.volume_id == vol_obj.id]
        vol_outlines = [o for o in db.get_outlines(novel_id) if o.volume_id == vol_obj.id]

        console.print(Panel(
            f"  [stat.label]小说:[/] [bold]{novel.title}[/] [muted](ID: {novel_id})[/]\n"
            f"  [stat.label]卷:[/] [bold]第{volume}卷 {vol_obj.title}[/]\n"
            f"\n"
            f"  [error]将删除以下数据:[/]\n"
            f"    章节: {len(vol_chapters)}\n"
            f"    大纲: {len(vol_outlines)}",
            title="[error]删除卷[/]",
            border_style="red",
            padding=(0, 2),
        ))

        if not force:
            confirmed = click.confirm("确认删除？此操作不可撤销", default=False)
            if not confirmed:
                console.print("[warning]已取消[/]")
                return

        ch_nums = [ch.chapter_number for ch in vol_chapters]
        deleted = db.delete_volume(novel_id, volume)

        try:
            from memory.chroma_store import ChromaStore
            chroma = ChromaStore(settings.chroma_persist_dir)
            if ch_nums:
                chroma.delete_chapter_data(novel_id, ch_nums)
        except Exception as e:
            console.print(f"[warning]向量记忆清除失败（不影响主数据）: {e}[/]")

        console.print(
            f"\n[success]第{volume}卷 '{vol_obj.title}' 已删除（{deleted}章）[/]"
        )
        return

    # ── Delete entire novel (original behavior) ──
    chapters = db.get_chapters(novel_id)
    characters = db.get_characters(novel_id)
    outlines = db.get_outlines(novel_id)
    world_settings = db.get_world_settings(novel_id) if hasattr(db, "get_world_settings") else []

    console.print(Panel(
        f"  [stat.label]小说:[/] [bold]{novel.title}[/] [muted](ID: {novel_id})[/]\n"
        f"  [stat.label]类型:[/] [genre]{novel.genre}[/]\n"
        f"\n"
        f"  [error]将删除以下数据:[/]\n"
        f"    章节: {len(chapters)}\n"
        f"    大纲: {len(outlines)}\n"
        f"    角色: {len(characters)}\n"
        f"    世界设定: {len(world_settings)}",
        title="[error]删除确认[/]",
        border_style="red",
        padding=(0, 2),
    ))

    if not force:
        confirmed = click.confirm("确认删除？此操作不可撤销", default=False)
        if not confirmed:
            console.print("[warning]已取消[/]")
            return

    # Delete from database
    db.delete_novel(novel_id)

    # Delete from vector store
    try:
        from memory.chroma_store import ChromaStore
        chroma = ChromaStore(settings.chroma_persist_dir)
        chroma.delete_novel_data(novel_id)
    except Exception as e:
        console.print(f"[warning]向量记忆清除失败（不影响主数据）: {e}[/]")

    console.print(f"\n[success]小说 '{novel.title}' (ID: {novel_id}) 已删除[/]")


# ---------------------------------------------------------------------------
# rebuild-memory command
# ---------------------------------------------------------------------------

@cli.command(name="rebuild-memory")
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
def rebuild_memory(novel_id):
    """重建指定小说的向量记忆库。

    当记忆库损坏或需要重新索引时使用。
    """
    from memory.chroma_store import ChromaStore
    from agents.memory_manager_agent import MemoryManagerAgent
    from tools.agent_sdk_client import AgentSDKClient

    settings = Settings()
    db = Database(settings.sqlite_db_path)

    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    chapters = db.get_chapters(novel_id)
    if not chapters:
        console.print("[warning]该小说没有任何章节[/]")
        return

    console.print(app_header())
    console.print()
    console.print(command_panel("重建记忆库", {
        "小说": f"{novel.title} (ID: {novel_id})",
        "章节数": str(len(chapters)),
    }))
    console.print()

    chroma = ChromaStore(settings.chroma_persist_dir)
    llm = AgentSDKClient(settings)
    memory_mgr = MemoryManagerAgent(db=db, chroma=chroma, llm_client=llm, settings=settings)

    # Clear existing memory for this novel
    chroma.delete_novel_data(novel_id)
    console.print(f"[muted]已清除小说 {novel_id} 的旧记忆数据[/]")

    # Re-index world settings
    world_settings = db.get_world_settings(novel_id)
    for ws in world_settings:
        chroma.add_world_event(
            novel_id=novel_id,
            chapter_number=0,
            event_description=f"[{ws.category}] {ws.name}: {ws.description}",
        )

    # Re-process each chapter
    async def _rebuild():
        with Progress(
            SpinnerColumn("dots"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("重建记忆...", total=len(chapters))

            for ch in chapters:
                if ch.content:
                    progress.update(task, description=f"处理第{ch.chapter_number}章...")
                    await memory_mgr.update_memory(novel_id, ch.chapter_number, ch.content)
                progress.advance(task)

    asyncio.run(_rebuild())
    console.print(f"\n[success]记忆重建完成！已处理 {len(chapters)} 章[/]")


# ---------------------------------------------------------------------------
# show command
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
@click.option("--chapter", "-c", required=True, type=int, help="章节号")
@click.option("--outline", "-o", is_flag=True, help="查看大纲而非正文")
def show(novel_id, chapter, outline):
    """查看某一章的正文或大纲。

    示例：
      opennovel show -n 1 -c 1
      opennovel show -n 1 -c 1 --outline
    """
    settings = Settings()
    db = Database(settings.sqlite_db_path)

    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    ch = db.get_chapter(novel_id, chapter)

    if outline:
        ol = db.get_outline(novel_id, chapter)
        if not ol:
            console.print(f"[error]未找到第 {chapter} 章的大纲[/]")
            sys.exit(1)

        # Meta info panel
        meta_parts = [f"  [stat.label]小说:[/] {novel.title} [muted](ID: {novel_id})[/]"]
        meta_parts.append(f"  [stat.label]章节:[/] 第{chapter}章")
        if ch and ch.title:
            meta_parts.append(f"  [stat.label]标题:[/] {ch.title}")
        if ol.emotional_tone:
            meta_parts.append(f"  [stat.label]情感基调:[/] {ol.emotional_tone}")
        if ol.hook_type:
            meta_parts.append(f"  [stat.label]钩子类型:[/] {ol.hook_type}")
        console.print(Panel(
            "\n".join(meta_parts),
            title="[bold]章节大纲[/]",
            border_style="dim",
            padding=(0, 2),
        ))
        console.print()

        # Outline text
        console.print("[bold]大纲内容[/]")
        console.print(ol.outline_text or "[muted]（空）[/]")
        console.print()

        # Key scenes
        if ol.key_scenes:
            console.print("[bold]关键场景[/]")
            console.print(ol.key_scenes)
            console.print()

    else:
        if not ch:
            console.print(f"[error]未找到第 {chapter} 章[/]")
            sys.exit(1)

        # Meta info panel
        status_str = ch.status.value if ch.status else "-"
        score_str = f"{ch.review_score:.1f}" if ch.review_score else "-"
        console.print(Panel(
            f"  [stat.label]小说:[/] {novel.title} [muted](ID: {novel_id})[/]\n"
            f"  [stat.label]章节:[/] 第{chapter}章  "
            f"[stat.label]标题:[/] {ch.title or '-'}\n"
            f"  [stat.label]字数:[/] [stat.value]{ch.char_count}[/]  "
            f"[stat.label]状态:[/] {status_str}  "
            f"[stat.label]评分:[/] {score_str}",
            title="[bold]章节信息[/]",
            border_style="dim",
            padding=(0, 2),
        ))
        console.print()

        # Content
        if ch.content:
            console.print(ch.content)
        else:
            console.print("[muted]（该章尚无正文内容）[/]")


# ---------------------------------------------------------------------------
# edit-chapter command
# ---------------------------------------------------------------------------

@cli.command(name="edit-chapter")
@click.option("--novel-id", "-n", required=True, type=int, help="小说ID")
@click.option("--chapter", "-c", required=True, type=int, help="章节号")
@click.option("--outline", "-o", is_flag=True, help="编辑大纲而非正文")
def edit_chapter(novel_id, chapter, outline):
    """用系统编辑器编辑章节正文或大纲，保存后写回数据库。

    示例：
      opennovel edit-chapter -n 1 -c 1
      opennovel edit-chapter -n 1 -c 1 --outline
    """
    settings = Settings()
    db = Database(settings.sqlite_db_path)

    novel = db.get_novel(novel_id)
    if not novel:
        console.print(f"[error]未找到ID为 {novel_id} 的小说[/]")
        sys.exit(1)

    if outline:
        ol = db.get_outline(novel_id, chapter)
        if not ol:
            console.print(f"[error]未找到第 {chapter} 章的大纲[/]")
            sys.exit(1)

        console.print(f"[info]正在打开第 {chapter} 章大纲编辑器...[/]")
        edited = click.edit(ol.outline_text or "", extension=".txt")
        if edited is None:
            console.print("[warning]编辑已取消（未修改或编辑器关闭）[/]")
            return

        ol.outline_text = edited.rstrip("\n")
        db.update_outline(ol)
        console.print(f"[success]第 {chapter} 章大纲已更新[/]")
    else:
        ch = db.get_chapter(novel_id, chapter)
        if not ch:
            console.print(f"[error]未找到第 {chapter} 章[/]")
            sys.exit(1)

        console.print(f"[info]正在打开第 {chapter} 章正文编辑器...[/]")
        edited = click.edit(ch.content or "", extension=".txt")
        if edited is None:
            console.print("[warning]编辑已取消（未修改或编辑器关闭）[/]")
            return

        ch.content = edited.rstrip("\n")
        ch.char_count = len(ch.content)
        db.update_chapter(ch)
        console.print(f"[success]第 {chapter} 章正文已更新（{ch.char_count} 字）[/]")


# ---------------------------------------------------------------------------
# edit-prompt command
# ---------------------------------------------------------------------------

_PROMPT_MAP = {
    "writer":          ("writer.md",          "写作智能体 — 章节创作风格与规则"),
    "editor":          ("editor.md",          "编辑智能体 — 润色、扩写、标点规范"),
    "reviewer":        ("reviewer.md",        "审核智能体 — 质量评分与问题检查"),
    "planner":         ("planner.md",         "规划总控 — 大纲生成流程"),
    "genre-research":  ("genre_research.md",  "类型研究 — 分析读者期待与套路"),
    "story-architect": ("story_architect.md", "故事架构 — 角色、世界、卷结构设计"),
    "conflict-design": ("conflict_design.md", "冲突设计 — 逐章大纲与冲突安排"),
    "memory-manager":  ("memory_manager.md",  "记忆管理 — 上下文检索与存储"),
}


@cli.command(name="edit-prompt")
@click.argument("name", required=False)
def edit_prompt(name):
    """查看或编辑智能体的 prompt 文件。

    不带参数列出所有可用 prompt；带参数用系统编辑器打开对应文件。

    示例：
      opennovel edit-prompt
      opennovel edit-prompt writer
      opennovel edit-prompt reviewer
    """
    prompts_dir = Path(__file__).resolve().parent.parent / "config" / "prompts"

    if not name:
        # List all prompts
        table = Table(title="可用 Prompt 文件", show_lines=False, border_style="dim")
        table.add_column("名称", style="bold")
        table.add_column("文件")
        table.add_column("说明")
        for pname, (filename, desc) in _PROMPT_MAP.items():
            exists = (prompts_dir / filename).exists()
            file_style = "" if exists else "dim"
            table.add_row(pname, f"[{file_style}]{filename}[/]", desc)
        console.print(table)
        console.print(f"\n[muted]用法: opennovel edit-prompt <名称>[/]")
        return

    if name not in _PROMPT_MAP:
        console.print(f"[error]未知的 prompt 名称: {name}[/]")
        console.print(f"[muted]可用名称: {', '.join(_PROMPT_MAP.keys())}[/]")
        sys.exit(1)

    filename, desc = _PROMPT_MAP[name]
    filepath = prompts_dir / filename

    if not filepath.exists():
        console.print(f"[error]文件不存在: {filepath}[/]")
        sys.exit(1)

    content = filepath.read_text(encoding="utf-8")
    console.print(f"[info]正在打开 {filename}（{desc}）...[/]")

    edited = click.edit(content, extension=".md")
    if edited is None:
        console.print("[warning]编辑已取消（未修改或编辑器关闭）[/]")
        return

    filepath.write_text(edited, encoding="utf-8")
    console.print(f"[success]{filename} 已更新[/]")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _print_usage_summary(final_state: dict) -> None:
    """Print LLM token usage and cost summary if available in final state."""
    usage = final_state.get("_llm_usage")
    if not usage:
        return
    total_tokens = usage.get("total_tokens", 0)
    total_cost = usage.get("total_cost_usd", 0.0)
    console.print(
        f"\n[muted]LLM用量: {total_tokens:,} tokens | "
        f"预估费用: ${total_cost:.4f}[/]"
    )


def main():
    """Entry point."""
    cli()


if __name__ == "__main__":
    main()
