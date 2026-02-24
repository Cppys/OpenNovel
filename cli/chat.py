"""OpenNovel — AI 代理式对话界面。

AI 可自主执行操作：用户描述需求，AI 通过动作指令自动调用工作流，
创建小说、写章节、读/改章节等。
"""

import json
import logging
import re
from typing import Optional

from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich import box

from cli.theme import get_console, NOVEL_THEME
from config.settings import Settings
from models.database import Database
from models.novel import Novel
from tools.agent_sdk_client import AgentSDKClient

logger = logging.getLogger(__name__)

# 最多保留的对话轮数（每轮 = 1 user + 1 assistant）
MAX_HISTORY_TURNS = 20

# ── 像素字 Banner ─────────────────────────────────────────────────────────

# 5 行高的 block-font 字母定义（每个字母宽度固定）
_LETTER_ART: dict[str, list[str]] = {
    '>': ["█▌   ", "███▌ ", "█████", "███▌ ", "█▌   "],
    'O': [" █████ ", "██   ██", "██   ██", "██   ██", " █████ "],
    'P': ["██████ ", "██   ██", "██████ ", "██     ", "██     "],
    'E': ["███████", "██     ", "█████  ", "██     ", "███████"],
    'N': ["██   ██", "███  ██", "██ █ ██", "██  ███", "██   ██"],
    'V': ["██   ██", "██   ██", " ██ ██ ", "  ███  ", "   █   "],
    'L': ["██     ", "██     ", "██     ", "██     ", "███████"],
}

# 字母序列 + 渐变配色（blue → purple → magenta → red）
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
    """构建带渐变色的 > OPENNOVEL 像素字 Banner。"""
    text = Text(justify="center")
    for line_idx in range(5):
        for i, (letter, color) in enumerate(_BANNER_WORD):
            text.append(_LETTER_ART[letter][line_idx], style=color)
            if i < len(_BANNER_WORD) - 1:
                text.append(" ")
        if line_idx < 4:
            text.append("\n")
    return text

# ── 动作解析 ──────────────────────────────────────────────────────────────

_ACTION_PATTERN = re.compile(r'<<<ACTION:\s*(\{.*?\})\s*>>>', re.DOTALL)


def parse_ai_response(response: str) -> tuple[str, list[dict]]:
    """从 AI 回复中提取文本和动作指令。

    动作格式：<<<ACTION: {"action": "...", ...}>>>

    Returns:
        (纯文本部分, 动作列表)
    """
    actions: list[dict] = []
    for match in _ACTION_PATTERN.finditer(response):
        try:
            actions.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            pass
    text = _ACTION_PATTERN.sub('', response).strip()
    return text, actions


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def _parse_chapter_range(chapters_str: str) -> list[int]:
    """解析章节范围字符串，如 '1-5', '3', '1,3,5'。"""
    chapters_str = chapters_str.strip()
    try:
        if "-" in chapters_str and "," not in chapters_str:
            parts = chapters_str.split("-", 1)
            start, end = int(parts[0]), int(parts[1])
            return list(range(start, end + 1))
        if "," in chapters_str:
            return sorted(set(int(x.strip()) for x in chapters_str.split(",")))
        return [int(chapters_str)]
    except (ValueError, IndexError):
        return []


def build_novel_context(db: Database, novel: Novel) -> str:
    """从数据库提取小说上下文信息，用于系统提示。"""
    parts = []

    # 基本信息
    parts.append(f"当前绑定小说：《{novel.title}》(ID: {novel.id})")
    parts.append(f"类型：{novel.genre}")
    if novel.synopsis:
        synopsis = novel.synopsis if len(novel.synopsis) <= 300 else novel.synopsis[:300] + "..."
        parts.append(f"简介：{synopsis}")

    # 章节概况
    chapters = db.get_chapters(novel.id)
    if chapters:
        total_chars = sum(ch.char_count for ch in chapters)
        parts.append(f"章节数：{len(chapters)}  总字数：{total_chars:,}")

    # 角色列表
    characters = db.get_characters(novel.id)
    if characters:
        char_lines = []
        for c in characters[:10]:
            role_str = c.role.value if hasattr(c.role, "value") else str(c.role)
            desc = c.description or ""
            if len(desc) > 50:
                desc = desc[:50] + "..."
            char_lines.append(f"  - {c.name}（{role_str}）：{desc}")
        parts.append("主要角色：\n" + "\n".join(char_lines))

    # 大纲摘要（只显示前几章）
    outlines = db.get_outlines(novel.id)
    if outlines:
        ol_lines = []
        for o in outlines[:5]:
            text = o.outline_text or ""
            if len(text) > 60:
                text = text[:60] + "..."
            ol_lines.append(f"  第{o.chapter_number}章：{text}")
        if len(outlines) > 5:
            ol_lines.append(f"  ...（共{len(outlines)}章大纲）")
        parts.append("大纲摘要：\n" + "\n".join(ol_lines))

    return "\n\n".join(parts)


def render_welcome(console, novel: Optional[Novel], db: Optional[Database] = None):
    """显示 OpenNovel 欢迎界面（Gemini CLI 风格）。"""
    # ── 像素字 Banner（深色面板）──
    banner = _build_banner()
    console.print(Panel(
        banner,
        style="on grey7",
        border_style="grey23",
        padding=(1, 2),
    ))

    # ── 模式 / 小说信息 ──
    if novel and db:
        chapters = db.get_chapters(novel.id)
        total_chars = sum(ch.char_count for ch in chapters) if chapters else 0
        console.print(
            f"\n[bold]{novel.title}[/] [dim]·[/] {novel.genre} [dim]·[/] "
            f"{len(chapters)}章 [dim]·[/] {total_chars:,}字"
        )
    else:
        console.print("\n[dim]通用写作助手模式[/]")
    console.print()

    # ── 两列：使用方法 + 快捷命令/小说信息 ──
    left = Text()
    left.append("使用方法\n", style="bold bright_red")
    left.append("/help        ", style="cyan")
    left.append("显示帮助\n", style="dim")
    left.append("/clear       ", style="cyan")
    left.append("清空对话历史\n", style="dim")
    left.append("/quit        ", style="cyan")
    left.append("退出\n", style="dim")

    right = Text()
    if novel and db:
        characters = db.get_characters(novel.id)
        right.append("提示\n", style="bold bright_red")
        right.append(f"使用 /novel <id> 绑定小说\n", style="dim")
        right.append(f"当前: ID {novel.id}  角色 {len(characters)}个\n", style="dim")
    else:
        right.append("提示\n", style="bold bright_red")
        right.append("直接对话，AI 自动执行操作\n", style="dim")
        right.append('"我想写一个玄幻小说"\n', style="dim")
        right.append('"写前5章" "给我看看第1章"\n', style="dim")

    table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2))
    table.add_column(ratio=3)
    table.add_column(ratio=2)
    table.add_row(left, right)
    console.print(table)
    console.print()


def render_ai_response(console, text: str):
    """用 Rich Markdown 渲染 AI 回复，带视觉标题。"""
    console.print()
    console.print(Text("◆", style="bold cyan"), end="  ")
    console.print(Markdown(text))
    console.print()


# ── 动作标签（用于状态显示）──────────────────────────────────────────────

_ACTION_LABELS: dict[str, str] = {
    "create_novel":     "创建小说",
    "write_chapters":   "写章节",
    "read_chapter":     "读取章节",
    "read_outline":     "读取大纲",
    "edit_chapter":     "修改章节",
    "list_chapters":    "获取章节列表",
    "list_characters":  "获取角色列表",
    "switch_novel":     "切换小说",
    "list_novels":      "获取小说列表",
    "delete_novel":     "删除小说",
    "publish_chapters": "上传番茄",
}

# ── 动作系统提示 ──────────────────────────────────────────────────────────

_ACTION_SYSTEM_PROMPT = """\
你可以执行以下操作来帮助用户创作小说。将动作嵌入回复末尾：
<<<ACTION: {"action": "动作名", ...参数}>>>

可用动作：
- create_novel: 创建新小说并生成大纲
  参数: genre(类型), premise(核心设定), chapters(总章节数,默认30),
        chapters_per_volume(每卷章节数,默认30), ideas(补充想法,可选)
- write_chapters: 写章节
  参数: novel_id(小说ID，不填则用当前绑定小说), chapters(如"1-5")
- read_chapter: 读取章节正文到对话上下文
  参数: chapter_number(章节号)
- read_outline: 读取章节大纲到对话上下文
  参数: chapter_number(章节号)
- edit_chapter: 直接更新章节内容
  参数: chapter_number(章节号), content(新内容)
- list_chapters: 列出所有章节
- list_characters: 列出所有角色
- switch_novel: 切换绑定小说
  参数: novel_id(小说ID)
- list_novels: 列出所有小说
- delete_novel: 删除小说及其所有数据（不可撤销！）
  参数: novel_id(小说ID，不填则删除当前绑定小说)
- publish_chapters: 将已审核章节上传到番茄小说
  参数: novel_id(可选), chapters(可选，如"1-5"，不填上传所有已审核章节),
        mode("publish"直接发布 或 "draft"保存草稿，默认"publish")

规则：
- 每条回复最多一个动作
- 先用文字解释你要做什么，然后在回复末尾放动作
- create_novel 执行前必须与用户确认以下参数（用户没说明的需询问，或用括号内默认值）：
  · 小说类型（genre）
  · 核心设定/故事创意（premise）
  · 总章节数（默认30章）
  · 每卷章节数（默认30章）
  · 补充想法（可选，如特定情节、角色安排等）
- write_chapters 执行前先确认章节范围
- delete_novel 是不可逆操作，必须用户明确再次确认后才能执行
- publish_chapters 需要用户事先完成 opennovel setup-browser 登录
- 动作的JSON必须是合法的JSON格式
"""


# ── ChatSession ───────────────────────────────────────────────────────────

class ChatSession:
    """管理 OpenNovel 对话状态、历史、动作执行和渲染。"""

    def __init__(self, db: Database, novel: Optional[Novel], settings: Settings):
        self.db = db
        self.novel = novel
        self.settings = settings
        self.llm = AgentSDKClient(settings)
        self.history: list[tuple[str, str]] = []  # (role, text)
        self.console = get_console()

    # ── 系统提示 ──────────────────────────────────────────────────────

    def build_system_prompt(self) -> str:
        """构建包含小说上下文和动作指令的系统提示。"""
        parts = [
            "你是 OpenNovel AI 写作助手，专注于中文网络小说创作。",
            "你可以帮助用户进行小说创作、修改、分析和讨论。",
            "回复时使用中文，格式清晰。如果用户让你写内容，直接给出内容，不要过多解释。",
        ]

        # 动作系统提示
        parts.append(_ACTION_SYSTEM_PROMPT)

        if self.novel:
            context = build_novel_context(self.db, self.novel)
            parts.append("--- 小说上下文 ---")
            parts.append(context)
            parts.append("--- 上下文结束 ---")
        else:
            # 列出已有小说供参考
            novels = self.db.list_novels()
            if novels:
                novel_list = "\n".join(
                    f"  {n.id}. 《{n.title}》({n.genre})"
                    for n in novels
                )
                parts.append(f"用户的小说列表：\n{novel_list}")
                parts.append("当前未绑定小说。如果用户想操作已有小说，使用 switch_novel 动作切换。")

        return "\n\n".join(parts)

    def format_user_prompt(self, message: str) -> str:
        """将对话历史 + 新消息格式化为完整 prompt。"""
        recent = self.history[-(MAX_HISTORY_TURNS * 2):]

        parts = []
        for role, text in recent:
            if role == "user":
                parts.append(f"Human: {text}")
            else:
                parts.append(f"Assistant: {text}")

        parts.append(f"Human: {message}")
        return "\n\n".join(parts)

    # ── 消息发送与动作执行 ────────────────────────────────────────────

    async def _llm_with_spinner(
        self,
        system_prompt: str,
        user_prompt: str,
        label: str = "思考中",
    ) -> str:
        """调用 LLM，同时用 Rich Live 显示动画状态指示器。

        状态变化：
          💭 思考中… → ✍️ 回复中… → (done, spinner disappears)
        """
        _phase: list[str] = [label]   # mutable for closure
        _live_ref: list = [None]

        def _make_renderable():
            if _phase[0] == "回复中":
                icon, txt = "✍️ ", "回复中"
            else:
                icon, txt = "💭 ", _phase[0]
            return Spinner("dots", text=Text.from_markup(f"  {icon}[dim]{txt}…[/dim]"))

        def on_event(event: dict):
            etype = event.get("type")
            live = _live_ref[0]
            if etype == "thinking" and _phase[0] == label:
                _phase[0] = "思考中"
                if live:
                    live.update(_make_renderable())
            elif etype == "text" and _phase[0] != "回复中":
                _phase[0] = "回复中"
                if live:
                    live.update(_make_renderable())

        with Live(
            _make_renderable(),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        ) as live:
            _live_ref[0] = live
            result = await self.llm.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.settings.llm_model_writing,
                on_event=on_event,
            )

        return result

    async def send(self, user_message: str) -> None:
        """发送消息、解析动作、执行动作；AI 可自动多步骤继续直到完成。

        渲染工作在此方法内完成，包括首次回复和所有续写回复。
        """
        MAX_AUTO_CONTINUES = 5

        # ── 第一次 LLM 调用（带动画状态）──
        system_prompt = self.build_system_prompt()
        user_prompt = self.format_user_prompt(user_message)

        response = await self._llm_with_spinner(system_prompt, user_prompt)
        text, actions = parse_ai_response(response)

        self.history.append(("user", user_message))
        self.history.append(("assistant", text))

        if text.strip():
            render_ai_response(self.console, text)

        # ── 自动继续循环（AI 执行 action 后继续思考）──
        for _ in range(MAX_AUTO_CONTINUES):
            if not actions:
                break

            action_results = []
            for action in actions:
                result = await self.execute_action(action)
                action_results.append(result)

            result_text = (
                "[系统] 动作执行结果：\n"
                + "\n".join(action_results)
                + "\n\n请继续回答用户的请求。"
            )

            system_prompt = self.build_system_prompt()
            user_prompt = self.format_user_prompt(result_text)

            response = await self._llm_with_spinner(
                system_prompt, user_prompt, label="继续思考"
            )
            text, actions = parse_ai_response(response)

            self.history.append(("user", result_text))
            self.history.append(("assistant", text))

            if text.strip():
                render_ai_response(self.console, text)

    # ── 动作分发 ──────────────────────────────────────────────────────

    async def execute_action(self, action: dict) -> str:
        """执行 AI 请求的动作，返回结果描述。"""
        name = action.get("action", "")
        label = _ACTION_LABELS.get(name, name)
        self.console.print()
        self.console.print(
            Text.from_markup(f"[bold cyan]⚡[/bold cyan]  [dim]{label}[/dim]")
        )
        try:
            if name == "create_novel":
                return await self._action_create_novel(action)
            elif name == "write_chapters":
                return await self._action_write_chapters(action)
            elif name == "read_chapter":
                return await self._action_read_chapter(action)
            elif name == "read_outline":
                return await self._action_read_outline(action)
            elif name == "edit_chapter":
                return await self._action_edit_chapter(action)
            elif name == "list_chapters":
                return self._action_list_chapters()
            elif name == "list_characters":
                return self._action_list_characters()
            elif name == "switch_novel":
                return self._action_switch_novel(action)
            elif name == "list_novels":
                return self._action_list_novels()
            elif name == "delete_novel":
                return self._action_delete_novel(action)
            elif name == "publish_chapters":
                return await self._action_publish_chapters(action)
            else:
                return f"未知动作: {name}"
        except Exception as e:
            logger.exception("Action '%s' failed", name)
            self.console.print(f"  [red]✗ 动作执行失败: {e}[/]")
            return f"动作 {name} 执行失败: {e}"

    # ── 具体动作实现 ──────────────────────────────────────────────────

    async def _action_create_novel(self, action: dict) -> str:
        """创建新小说并生成大纲。"""
        from workflow.graph import run_workflow
        from workflow.callbacks import ChatProgressCallback

        genre = action.get("genre", "")
        premise = action.get("premise", "")
        chapters = action.get("chapters", 30)
        chapters_per_volume = action.get("chapters_per_volume", 30)
        ideas = action.get("ideas", "")

        if not genre or not premise:
            return "create_novel 失败: 缺少 genre 或 premise 参数"

        self.console.print()
        self.console.print(
            f"  [dim]创建小说: {genre} · {premise} · "
            f"{chapters}章 · 每卷{chapters_per_volume}章[/]"
        )

        cb = ChatProgressCallback(console=self.console)
        final_state = await run_workflow(
            mode="plan_only",
            genre=genre,
            premise=premise,
            ideas=ideas,
            target_chapters=int(chapters),
            chapters_per_volume=int(chapters_per_volume),
            callback=cb,
        )

        error = final_state.get("error", "")
        if error:
            return f"create_novel 失败: {error}"

        novel_id = final_state.get("novel_id", 0)
        # 自动绑定到新创建的小说
        novel = self.db.get_novel(novel_id)
        if novel:
            self.novel = novel
            title = novel.title
            outlines = self.db.get_outlines(novel_id)
            characters = self.db.get_characters(novel_id)
            return (
                f"小说创建成功！《{title}》(ID: {novel_id})\n"
                f"  章节大纲: {len(outlines)}章\n"
                f"  角色: {len(characters)}个\n"
                f"  已自动绑定到该小说"
            )
        return f"小说创建成功 (ID: {novel_id})"

    async def _action_write_chapters(self, action: dict) -> str:
        """写章节。"""
        from workflow.graph import run_workflow
        from workflow.callbacks import ChatProgressCallback

        novel_id = action.get("novel_id")
        chapters_str = str(action.get("chapters", ""))

        # 如果未指定 novel_id，使用当前绑定的小说
        if not novel_id and self.novel:
            novel_id = self.novel.id
        if not novel_id:
            return "write_chapters 失败: 未指定 novel_id 且未绑定小说"

        novel = self.db.get_novel(novel_id)
        if not novel:
            return f"write_chapters 失败: 未找到 ID 为 {novel_id} 的小说"

        chapter_list = _parse_chapter_range(chapters_str)
        if not chapter_list:
            return f"write_chapters 失败: 无效的章节范围 '{chapters_str}'"

        self.console.print()
        self.console.print(
            f"  [dim]写作《{novel.title}》"
            f"第{chapter_list[0]}-{chapter_list[-1]}章"
            f"（共{len(chapter_list)}章）[/]"
        )

        cb = ChatProgressCallback(console=self.console)
        final_state = await run_workflow(
            mode="continue",
            novel_id=novel_id,
            genre=novel.genre,
            chapter_list=chapter_list,
            callback=cb,
        )

        error = final_state.get("error", "")
        if error:
            return f"write_chapters 失败: {error}"

        written = final_state.get("chapters_written", 0)
        all_chapters = self.db.get_chapters(novel_id)
        total_chars = sum(ch.char_count for ch in all_chapters)

        # 计算新写章节的平均评分
        written_nums = set(chapter_list)
        new_chapters = [ch for ch in all_chapters if ch.chapter_number in written_nums]
        scores = [ch.review_score for ch in new_chapters if ch.review_score]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # 确保绑定到该小说
        self.novel = novel

        return (
            f"写作完成！新增 {written} 章\n"
            f"  总字数: {total_chars:,}\n"
            f"  平均评分: {avg_score:.1f}"
        )

    async def _action_read_chapter(self, action: dict) -> str:
        """读取章节正文到上下文。"""
        chapter_num = action.get("chapter_number")
        if chapter_num is None:
            return "read_chapter 失败: 缺少 chapter_number 参数"

        if not self.novel:
            return "read_chapter 失败: 未绑定小说"

        chapter = self.db.get_chapter(self.novel.id, int(chapter_num))
        if not chapter:
            return f"read_chapter 失败: 未找到第 {chapter_num} 章"

        if not chapter.content:
            return f"第 {chapter_num} 章尚无正文内容"

        # 注入到对话历史
        inject_text = (
            f"[系统] 以下是《{self.novel.title}》第{chapter_num}章"
            f"（{chapter.title or '无标题'}，{chapter.char_count}字）的正文：\n\n"
            f"{chapter.content}"
        )
        self.history.append(("user", inject_text))

        self.console.print(
            f"  [green]✓[/] 已加载第{chapter_num}章"
            f"（{chapter.title or '无标题'}，{chapter.char_count}字）"
        )
        return (
            f"已加载第{chapter_num}章 "
            f"《{chapter.title or '无标题'}》({chapter.char_count}字) 到对话上下文"
        )

    async def _action_read_outline(self, action: dict) -> str:
        """读取章节大纲到上下文。"""
        chapter_num = action.get("chapter_number")
        if chapter_num is None:
            return "read_outline 失败: 缺少 chapter_number 参数"

        if not self.novel:
            return "read_outline 失败: 未绑定小说"

        outline = self.db.get_outline(self.novel.id, int(chapter_num))
        if not outline:
            return f"read_outline 失败: 未找到第 {chapter_num} 章的大纲"

        parts = [f"[系统] 以下是《{self.novel.title}》第{chapter_num}章的大纲："]
        parts.append(outline.outline_text or "（空）")
        if outline.key_scenes:
            parts.append(f"\n关键场景：{outline.key_scenes}")
        if outline.emotional_tone:
            parts.append(f"情感基调：{outline.emotional_tone}")

        inject_text = "\n".join(parts)
        self.history.append(("user", inject_text))

        self.console.print(f"  [green]✓[/] 已加载第{chapter_num}章大纲")
        return f"已加载第{chapter_num}章大纲到对话上下文"

    async def _action_edit_chapter(self, action: dict) -> str:
        """直接更新章节内容。"""
        chapter_num = action.get("chapter_number")
        content = action.get("content", "")

        if chapter_num is None:
            return "edit_chapter 失败: 缺少 chapter_number 参数"
        if not content:
            return "edit_chapter 失败: 缺少 content 参数"
        if not self.novel:
            return "edit_chapter 失败: 未绑定小说"

        chapter = self.db.get_chapter(self.novel.id, int(chapter_num))
        if not chapter:
            return f"edit_chapter 失败: 未找到第 {chapter_num} 章"

        chapter.content = content.strip()
        chapter.char_count = len(chapter.content)
        self.db.update_chapter(chapter)

        self.console.print(
            f"  [green]✓[/] 第{chapter_num}章已更新（{chapter.char_count:,}字）"
        )
        return f"第{chapter_num}章已更新（{chapter.char_count:,}字）"

    def _action_list_chapters(self) -> str:
        """列出所有章节。"""
        if not self.novel:
            return "list_chapters: 未绑定小说"

        chapters = self.db.get_chapters(self.novel.id)
        if not chapters:
            return f"《{self.novel.title}》暂无章节"

        lines = [f"《{self.novel.title}》章节列表："]
        for ch in chapters:
            status_str = ch.status.value if ch.status else "-"
            title = ch.title or "无标题"
            lines.append(
                f"  第{ch.chapter_number}章 {title}"
                f" ({ch.char_count}字 · {status_str})"
            )

        result = "\n".join(lines)
        self.console.print(f"  [green]✓[/] 共{len(chapters)}章")
        return result

    def _action_list_characters(self) -> str:
        """列出所有角色。"""
        if not self.novel:
            return "list_characters: 未绑定小说"

        characters = self.db.get_characters(self.novel.id)
        if not characters:
            return f"《{self.novel.title}》暂无角色"

        lines = [f"《{self.novel.title}》角色列表："]
        for c in characters:
            role_str = c.role.value if hasattr(c.role, "value") else str(c.role)
            desc = c.description or ""
            if len(desc) > 80:
                desc = desc[:80] + "..."
            lines.append(f"  {c.name}（{role_str}）：{desc}")

        result = "\n".join(lines)
        self.console.print(f"  [green]✓[/] 共{len(characters)}个角色")
        return result

    def _action_switch_novel(self, action: dict) -> str:
        """切换绑定小说。"""
        novel_id = action.get("novel_id")
        if novel_id is None:
            return "switch_novel 失败: 缺少 novel_id 参数"

        novel = self.db.get_novel(int(novel_id))
        if not novel:
            return f"switch_novel 失败: 未找到 ID 为 {novel_id} 的小说"

        self.novel = novel
        # 不清空历史——保留对话上下文，让 AI 能在 switch_novel 后继续回答

        chapters = self.db.get_chapters(novel.id)
        total_chars = sum(ch.char_count for ch in chapters) if chapters else 0

        self.console.print(
            f"  [green]✓[/] 已切换到《{novel.title}》"
            f"（{novel.genre} · {len(chapters)}章 · {total_chars:,}字）"
        )
        return (
            f"已切换到《{novel.title}》(ID: {novel.id})\n"
            f"  类型: {novel.genre}\n"
            f"  章节: {len(chapters)}章\n"
            f"  总字数: {total_chars:,}\n"
            f"  对话历史已清空"
        )

    def _action_list_novels(self) -> str:
        """列出所有小说。"""
        novels = self.db.list_novels()
        if not novels:
            return "暂无小说记录"

        lines = ["小说列表："]
        for n in novels:
            marker = " <- 当前" if self.novel and n.id == self.novel.id else ""
            lines.append(f"  {n.id}. 《{n.title}》({n.genre}){marker}")

        result = "\n".join(lines)
        self.console.print(f"  [green]✓[/] 共{len(novels)}部小说")
        return result

    def _action_delete_novel(self, action: dict) -> str:
        """删除小说及其所有数据。"""
        novel_id = action.get("novel_id")
        if novel_id is None:
            if self.novel:
                novel_id = self.novel.id
            else:
                return "delete_novel 失败: 缺少 novel_id 参数且未绑定小说"

        novel = self.db.get_novel(int(novel_id))
        if not novel:
            return f"delete_novel 失败: 未找到 ID 为 {novel_id} 的小说"

        title = novel.title
        self.db.delete_novel(int(novel_id))

        # 清除向量记忆
        try:
            from memory.chroma_store import ChromaStore
            chroma = ChromaStore(self.settings.chroma_persist_dir)
            chroma.delete_novel_data(int(novel_id))
        except Exception as e:
            logger.warning("Chroma delete failed for novel %s: %s", novel_id, e)

        # 如果删的是当前绑定小说，解绑
        if self.novel and self.novel.id == int(novel_id):
            self.novel = None

        self.console.print(f"  [green]✓[/] 已删除《{title}》(ID: {novel_id})")
        return f"已删除《{title}》(ID: {novel_id}) 及其所有章节、大纲、角色数据"

    async def _action_publish_chapters(self, action: dict) -> str:
        """将已审核章节上传到番茄小说。"""
        import asyncio
        from agents.publisher_agent import PublisherAgent
        from models.enums import ChapterStatus

        novel_id = action.get("novel_id")
        chapters_str = str(action.get("chapters", "all"))
        mode = action.get("mode", "publish")

        if not novel_id and self.novel:
            novel_id = self.novel.id
        if not novel_id:
            return "publish_chapters 失败: 未指定 novel_id 且未绑定小说"

        novel = self.db.get_novel(int(novel_id))
        if not novel:
            return f"publish_chapters 失败: 未找到 ID 为 {novel_id} 的小说"

        # 获取待上传（已审核）章节
        reviewed = self.db.get_chapters(int(novel_id), ChapterStatus.REVIEWED)
        if not reviewed:
            return f"publish_chapters: 《{novel.title}》没有待上传的已审核章节（需先用 write_chapters 写章节）"

        # 筛选章节范围
        if chapters_str != "all":
            selected = set(_parse_chapter_range(chapters_str))
            reviewed = [ch for ch in reviewed if ch.chapter_number in selected]
            if not reviewed:
                return "publish_chapters: 所选范围内没有待上传的已审核章节"

        publisher = PublisherAgent(settings=self.settings)

        # 如果没有番茄书 ID，先自动建书
        if not novel.fanqie_book_id:
            self.console.print(f"  [dim]该小说尚未在番茄建书，正在自动创建...[/]")
            characters = self.db.get_characters(int(novel_id))
            protagonists = [c for c in characters
                            if getattr(c.role, "value", str(c.role)) == "protagonist"]
            pname1 = protagonists[0].name if len(protagonists) > 0 else ""
            pname2 = protagonists[1].name if len(protagonists) > 1 else ""
            try:
                book_id = await asyncio.to_thread(
                    publisher.create_book_sync,
                    novel.title, novel.genre, novel.synopsis or "",
                    pname1, pname2,
                )
                if book_id:
                    novel.fanqie_book_id = book_id
                    self.db.update_novel(novel)
                    self.console.print(f"  [green]✓[/] 番茄建书成功 (book_id: {book_id})")
                else:
                    return "publish_chapters 失败: 自动建书返回空 book_id，请先运行 opennovel setup-browser 登录"
            except Exception as e:
                return f"publish_chapters 失败: 自动建书失败 ({e})，请先运行 opennovel setup-browser 登录"

        # 上传章节
        self.console.print(f"  [dim]上传 {len(reviewed)} 章到番茄（模式: {mode}）...[/]")
        chapter_data = [
            {"chapter_number": ch.chapter_number, "title": ch.title, "content": ch.content or ""}
            for ch in reviewed
        ]
        try:
            results = await asyncio.to_thread(
                publisher.publish_sync,
                novel.fanqie_book_id, chapter_data, mode,
            )
        except Exception as e:
            return f"publish_chapters 失败: 上传出错 ({e})"

        success_count = 0
        for ch, result in zip(reviewed, results):
            if result.get("success"):
                success_count += 1
                ch.status = ChapterStatus.PUBLISHED
                ch.fanqie_chapter_id = result.get("item_id", "")
                self.db.update_chapter(ch)
                self.console.print(
                    f"  [green]✓[/] 第{ch.chapter_number}章 "
                    f"{'已发布' if mode == 'publish' else '草稿已保存'}"
                )
            else:
                self.console.print(
                    f"  [red]✗[/] 第{ch.chapter_number}章失败: "
                    f"{result.get('message', '未知错误')}"
                )

        return f"上传完成：成功 {success_count}/{len(reviewed)} 章"

    # ── 斜杠命令（精简版）────────────────────────────────────────────

    def handle_command(self, cmd: str) -> Optional[str]:
        """处理斜杠命令。返回显示文本或 None（退出）。"""
        cmd = cmd.strip()
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()

        if command in ("/quit", "/exit"):
            return None

        if command == "/help":
            return self._cmd_help()

        if command == "/clear":
            return self._cmd_clear()

        return f"[error]未知命令: {command}[/]\n输入 /help 查看可用命令"

    def _cmd_help(self) -> str:
        lines = [
            "[bold]快捷命令[/]",
            "",
            "  [accent]/help[/]    显示本帮助",
            "  [accent]/quit[/]    退出对话",
            "  [accent]/clear[/]   清空对话历史",
            "",
            "[bold]AI 代理模式[/]",
            "",
            "  直接用自然语言告诉 AI 你想做什么，AI 会自动执行操作：",
            "  · \"我想写一个玄幻小说\"    → AI 确认设定后创建大纲",
            "  · \"写前5章\"              → AI 调用工作流写章节",
            "  · \"给我看看第1章\"         → AI 加载章节内容",
            "  · \"帮我改一下第3章的开头\"  → AI 读取并修改章节",
            "  · \"列出所有角色\"          → AI 查询角色列表",
        ]
        return "\n".join(lines)

    def _cmd_clear(self) -> str:
        self.history.clear()
        return "[success]对话历史已清空[/]"

    # ── 主循环 ────────────────────────────────────────────────────────

    async def run(self):
        """主对话循环。"""
        render_welcome(self.console, self.novel, self.db)

        # ── 状态栏 ──
        model = self.settings.llm_model_writing
        path = f"~/opennovel/{self.novel.id}" if self.novel else "~/opennovel"
        status = Table(show_header=False, show_edge=False, box=None, expand=True, padding=0)
        status.add_column(ratio=1)
        status.add_column(ratio=1, justify="center")
        status.add_column(ratio=1, justify="right")
        status.add_row(
            f"[dim]{path}[/]",
            "[dim]chat-mode[/]",
            f"[dim]{model}[/]",
        )
        self.console.print(status)
        self.console.print()

        while True:
            # ── 边框输入框 ──
            w = max(self.console.size.width - 2, 20)
            self.console.print(f"[dim]╭{'─' * (w - 2)}╮[/]")
            try:
                user_input = self.console.input("[dim]│[/] [bright_blue]>[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print(f"[dim]╰{'─' * (w - 2)}╯[/]")
                self.console.print("\n[muted]再见！[/]")
                break
            self.console.print(f"[dim]╰{'─' * (w - 2)}╯[/]")

            if not user_input:
                continue

            # 斜杠命令
            if user_input.startswith("/"):
                result = self.handle_command(user_input)
                if result is None:
                    self.console.print("[muted]再见！[/]")
                    break
                self.console.print(result)
                self.console.print()
                continue

            # 普通对话 — 发送给 AI，AI 可能触发动作并自动继续
            try:
                await self.send(user_input)
            except KeyboardInterrupt:
                self.console.print("\n[warning]已中断当前回复[/]")
            except Exception as e:
                self.console.print(f"\n[error]AI 回复失败：{e}[/]")
                logger.exception("Chat send failed")
