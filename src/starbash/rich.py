from collections.abc import Iterable
from typing import Any

from rich.tree import Tree

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
