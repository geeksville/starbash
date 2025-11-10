#!/usr/bin/env python3
"""Pre-commit hook to validate Python imports can be resolved."""

import sys
from pathlib import Path


def check_imports():
    """Try to import all Python modules to catch import errors early."""
    errors = []
    src_path = Path("src")

    if not src_path.exists():
        print("Error: src directory not found", file=sys.stderr)
        return 1

    # Add src to path so imports work
    sys.path.insert(0, str(src_path))

    for py_file in src_path.rglob("*.py"):
        # Skip __pycache__ and other cache files
        if "__pycache__" in str(py_file):
            continue

        # Convert file path to module name
        rel_path = py_file.relative_to(src_path)
        module_name = str(rel_path.with_suffix("")).replace("/", ".")

        # Skip __init__ at the end
        if module_name.endswith(".__init__"):
            module_name = module_name[:-9]

        try:
            __import__(module_name)
        except ImportError as e:
            errors.append(f"{py_file}: {e}")
        except Exception as e:
            # Other exceptions (like missing dependencies) are OK
            # We only care about import structure errors
            if "cannot import name" in str(e).lower():
                errors.append(f"{py_file}: {e}")

    if errors:
        print("Import validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(check_imports())
