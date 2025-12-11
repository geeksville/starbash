from typing import Any

# Utility functions for safely doing common operations, throwing user friendly errors to be caught
# upstream at the proper level.  i.e. for the common case we guarantee we don't return None.
# FIXME: have users pass in an optional human-friendly string to make nice error messages.


def get_safe[T](d: dict[str, T], key: Any) -> T:
    """Get a value from the given dictionary key, raising an error if missing."""
    names: T | None = d.get(key)
    if names is None:
        raise ValueError(f"Config is missing '{key}' field")
    return names


def get_list_of_strings(d: dict[str, Any], key: str) -> list[str]:
    """Get a list of strings from the given dictionary key.

    If the value is a single string, it is wrapped in a list.
    If the value is already a list of strings, it is returned as is.
    If the key does not exist, an empty list is returned.

    Args:
        d: The dictionary to extract from
        key: The key to look for"""
    names: str | list[str] | None = get_safe(d, key)
    if isinstance(names, str):
        names = [names]
    elif not isinstance(names, list):
        raise ValueError(f"Expected string or list of strings for key '{key}', got {type(names)}")
    return names
