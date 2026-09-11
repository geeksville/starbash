from collections.abc import Iterable
from io import StringIO
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.tree import Tree

from starbash.url import make_file_url

BRIEF_LIMIT = 3  # Maximum number of leaf items to show in brief mode


def to_tree(obj: Any, label: str = "root", brief: bool = True) -> Tree:
    """Given any object, recursively descend through it to generate a nice nested Tree

    Args:
        obj: Object to convert to a tree (dict, list, or any other type)
        label: Label for the root node
        brief: If True, limit the number of leaf items shown

    Returns:
        A Rich Tree object representing the structure
    """
    tree = Tree(label)

    minor_count = 0  # count of minor items skipped for brevity
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, dict) or (
                isinstance(value, Iterable) and not isinstance(value, str)
            ):
                # Recursively create a subtree for nested collections
                subtree = to_tree(value, label=str(key), brief=brief)
                tree.add(subtree)
            else:
                # Add simple key-value pairs as leaves
                minor_count += 1
                if not brief or minor_count <= BRIEF_LIMIT:
                    value_str = str(value)
                    if len(value_str) > 80:
                        value_str = value_str[:80] + "…"
                    tree.add(f"[bold]{key}[/bold]: {value_str}")
    elif isinstance(obj, Iterable) and not isinstance(obj, str):
        for i, item in enumerate(obj):
            if isinstance(item, dict) or (isinstance(item, Iterable) and not isinstance(item, str)):
                # Recursively create a subtree for nested collections
                item_tree = to_tree(item, label=f"[{i}]", brief=brief)
                tree.add(item_tree)
            else:
                minor_count += 1
                if not brief or minor_count <= BRIEF_LIMIT:
                    tree.add(f"[{i}]: {item}")
    else:
        # For any other type, just tostr
        tree.add(f"{obj}")

    # Show how many items were skipped
    if brief and minor_count > BRIEF_LIMIT:
        tree.add(f"[dim]… and {minor_count - BRIEF_LIMIT} more[/dim]")

    return tree


def to_rich_link(f: str | Path, label: str | None = None) -> str:
    """Create a Rich-formatted clickable link to a file path.

    Args:
        f: Path to the file
        label: Optional label for the link; if None, uses the file name"""
    if isinstance(f, str):  # assume URL
        file_url = str(f)
        fdefault = f
    elif isinstance(f, Path):
        file_url = make_file_url(f)
        fdefault = f.name
    else:
        raise TypeError("f must be a Path or Url")

    link_label = label or fdefault
    return f"[link={file_url}]{link_label}[/link]"


def _file_ref_links(refs: Iterable[Any]) -> str:
    """Render a list of plain ``{label, url}`` file refs as clickable Rich links."""
    parts: list[str] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        label = ref.get("label") or ""
        url = ref.get("url")
        parts.append(to_rich_link(url, label) if url else label)
    return ", ".join(parts)


def run_tree_to_rich(run: dict[str, Any], root_label: str | None = None) -> Tree:
    """Render a plain run-tree dict (from ``RunTree.to_plain()``) as a Rich Tree.

    The tree is ``target -> stage -> tasks`` with a status glyph per node, a dim
    log tail, and clickable links for outputs, the recipe toml and the target
    config.  Shared by the CLI's live processing view.
    """
    from starbash.run_state import RunStatus

    target = run.get("target") or "masters"
    label = root_label or f"[bold]{target}[/bold]"
    if run.get("output_url"):
        label += f"  [dim]{to_rich_link(run['output_url'], '→ output')}[/dim]"
    tree = Tree(label, guide_style="dim")

    for stage in run.get("stages", []):
        if not isinstance(stage, dict):
            continue
        status = RunStatus(stage.get("status", RunStatus.PENDING))
        if stage.get("excluded"):
            head = f"[dim]{RunStatus.EXCLUDED.glyph} {stage.get('name')} (excluded)[/dim]"
        else:
            head = (
                f"[{status.rich_style}]{status.glyph} {stage.get('name')}[/{status.rich_style}]"
            )
        if stage.get("dependencies"):
            head += f" [dim]← {', '.join(stage['dependencies'])}[/dim]"
        if stage.get("recipe_url"):
            head += " " + to_rich_link(stage["recipe_url"], "recipe")
        if stage.get("config_url"):
            head += " " + to_rich_link(stage["config_url"], "config")
        branch = tree.add(head)

        for line in stage.get("logs", []):
            branch.add(f"[dim]{line}[/dim]")

        outputs = _file_ref_links(stage.get("outputs", []))
        if outputs:
            branch.add(f"[dim]out:[/dim] {outputs}")

        for task in stage.get("tasks", []):
            if not isinstance(task, dict):
                continue
            tstatus = RunStatus(task.get("status", RunStatus.PENDING))
            row = (
                f"[{tstatus.rich_style}]{tstatus.glyph}[/{tstatus.rich_style}] "
                f"{task.get('title') or task.get('name')}"
            )
            if task.get("session"):
                row += f" [dim]{task['session']}[/dim]"
            if task.get("reason"):
                row += f" [dim]({task['reason']})[/dim]"
            task_out = _file_ref_links(task.get("outputs", []))
            if task_out:
                row += f" [dim]→[/dim] {task_out}"
            branch.add(row)

    return tree


def to_rich_string(obj: Any) -> str:
    """Render any object to a Rich formatted string."""

    string_io = StringIO()
    temp_console = Console(file=string_io, force_terminal=True, width=120, record=True)
    temp_console.print(obj)
    return temp_console.export_text()
