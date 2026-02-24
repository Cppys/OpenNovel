"""Unified Rich theme and reusable UI helper functions for the CLI."""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.theme import Theme
from rich.tree import Tree

NOVEL_THEME = Theme({
    "app.title": "bold",
    "success": "green",
    "warning": "yellow",
    "error": "red",
    "info": "blue",
    "muted": "dim",
    "accent": "cyan",
    "genre": "bold",
    "stat.label": "dim",
    "stat.value": "bold",
    "chapter.num": "blue",
    "character.name": "bold cyan",
})


def get_console() -> Console:
    """Return a Console instance with the novel theme applied."""
    return Console(theme=NOVEL_THEME)


def app_header(title: str = "opennovel") -> Rule:
    """Return a Rule element for the application header banner."""
    return Rule(title=f"[bold]{title}[/]", style="dim")


def command_panel(title: str, fields: dict[str, str]) -> Panel:
    """Return a Panel displaying command parameters.

    Args:
        title: Panel title (e.g. "创建新小说").
        fields: Ordered dict of label -> value pairs.
    """
    lines = []
    for label, value in fields.items():
        lines.append(f"  [stat.label]{label}:[/] [stat.value]{value}[/]")
    body = "\n".join(lines)
    return Panel(body, title=f"[bold]{title}[/]", box=box.ROUNDED, border_style="dim", padding=(0, 2))


def success_panel(title: str, body: str) -> Panel:
    """Return a green-bordered Panel for success results."""
    return Panel(body, title=f"[success]{title}[/]", box=box.ROUNDED, border_style="green", padding=(0, 2))


def novel_summary_panel(novel, characters: list, outlines: list) -> Panel:
    """Return a Panel with novel summary stats.

    Args:
        novel: Novel ORM object with .title, .genre, .synopsis, .id attributes.
        characters: List of Character objects.
        outlines: List of Outline objects.
    """
    synopsis = novel.synopsis or ""
    if len(synopsis) > 150:
        synopsis = synopsis[:150] + "..."

    body = (
        f"  [stat.label]类型:[/] [genre]{novel.genre}[/]  "
        f"[muted]|[/]  [stat.label]角色:[/] [stat.value]{len(characters)}[/]  "
        f"[muted]|[/]  [stat.label]章节:[/] [stat.value]{len(outlines)}[/]\n"
        f"  [stat.label]简介:[/] {synopsis}"
    )
    return Panel(
        body,
        title=f"[bold]{novel.title}[/] [muted](ID: {novel.id})[/]",
        box=box.ROUNDED,
        border_style="dim",
        padding=(0, 2),
    )


def volume_tree(volumes_data: list[dict]) -> Tree:
    """Build a Rich Tree showing the volume/chapter structure.

    Args:
        volumes_data: List of volume dicts, each with 'title', 'volume_number',
                      and 'chapters' (list of dicts with 'chapter_number').
    """
    tree = Tree("[bold]卷章结构[/]")
    for vol in volumes_data:
        vol_num = vol.get("volume_number", "?")
        vol_title = vol.get("title", "")
        vol_branch = tree.add(f"[bold cyan]第{vol_num}卷[/] {vol_title}")
        chapters = vol.get("chapters", [])
        for ch in chapters[:5]:
            ch_num = ch.get("chapter_number", "?")
            outline_text = ch.get("outline", "")
            short = (outline_text[:30] + "...") if len(outline_text) > 30 else outline_text
            vol_branch.add(f"[chapter.num]第{ch_num}章[/] {short}")
        if len(chapters) > 5:
            vol_branch.add(f"[muted]... (共{len(chapters)}章)[/]")
    return tree


def character_cards(characters: list) -> Table:
    """Build a Rich Table layout of character information.

    Args:
        characters: List of character objects or dicts with name, role, description.
    """
    table = Table(box=box.ROUNDED, border_style="dim", show_header=True, padding=(0, 1))
    table.add_column("角色", style="character.name")
    table.add_column("类型", style="muted")
    table.add_column("描述")

    for c in characters[:8]:
        if isinstance(c, dict):
            name = c.get("name", "?")
            role = c.get("role", "")
            desc = c.get("description", "")
        else:
            name = getattr(c, "name", "?")
            role = getattr(c, "role", "")
            if hasattr(role, "value"):
                role = role.value
            desc = getattr(c, "description", "")

        if len(desc) > 40:
            desc = desc[:40] + "..."

        table.add_row(name, role, desc)

    if len(characters) > 8:
        table.add_row(f"[muted]+{len(characters) - 8} more[/]", "", "")

    return table


def outline_tree_from_db(outlines: list, volumes: list = None) -> Tree:
    """Build a Rich Tree from DB outline/volume objects.

    Args:
        outlines: List of Outline ORM objects with chapter_number, outline_text, volume_id.
        volumes: Optional list of Volume ORM objects.
    """
    tree = Tree("[bold]卷章结构[/]")

    if volumes:
        vol_map: dict[int, list] = {}
        for o in outlines:
            vol_map.setdefault(o.volume_id, []).append(o)

        for vol in volumes:
            vol_branch = tree.add(
                f"[bold cyan]第{vol.volume_number}卷[/] {vol.title}"
            )
            vol_outlines = vol_map.get(vol.id, [])
            vol_outlines.sort(key=lambda x: x.chapter_number)
            for o in vol_outlines[:5]:
                short = (o.outline_text[:30] + "...") if len(o.outline_text or "") > 30 else (o.outline_text or "")
                vol_branch.add(f"[chapter.num]第{o.chapter_number}章[/] {short}")
            if len(vol_outlines) > 5:
                vol_branch.add(f"[muted]... (共{len(vol_outlines)}章)[/]")
    else:
        for o in outlines[:10]:
            short = (o.outline_text[:40] + "...") if len(o.outline_text or "") > 40 else (o.outline_text or "")
            tree.add(f"[chapter.num]第{o.chapter_number}章[/] {short}")
        if len(outlines) > 10:
            tree.add(f"[muted]... (共{len(outlines)}章)[/]")

    return tree
