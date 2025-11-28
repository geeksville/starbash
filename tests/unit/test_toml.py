"""Test tomlkit library behavior to investigate potential bugs.

This test suite explores how tomlkit handles various data structures,
particularly focusing on array-of-tables (AoT) manipulation patterns
used in starbash's ProcessedTarget._update_from_context() method.
"""

import tomlkit
from tomlkit import aot, array, item, table
from tomlkit.items import AoT


def test_basic_aot_creation():
    """Test basic array-of-tables creation."""
    doc = tomlkit.document()

    # Create an AoT
    sessions = aot()

    # Add a table to it
    session1 = table()
    session1["id"] = 1
    session1["name"] = "test"
    sessions.append(session1)

    doc["sessions"] = sessions

    result = doc.as_string()
    print("Basic AoT creation:")
    print(result)
    print()

    # Verify it's valid TOML
    assert "[[sessions]]" in result
    assert "id = 1" in result
    assert 'name = "test"' in result


def test_aot_with_nested_structures():
    """Test AoT with nested tables and arrays."""
    doc = tomlkit.document()

    sessions = aot()

    # Create a session with nested structures
    session = table()
    session["id"] = 1
    session["filter"] = "Ha"
    session["exptime_total"] = 120.5

    # Add nested table
    metadata = table()
    metadata["SIMPLE"] = True
    metadata["BITPIX"] = 16
    metadata["INSTRUME"] = "TELE"
    session["metadata"] = metadata

    # Add nested array
    files = array()
    files.append("file1.fits")
    files.append("file2.fits")
    session["files"] = files

    sessions.append(session)
    doc["sessions"] = sessions

    result = doc.as_string()
    print("AoT with nested structures:")
    print(result)
    print()

    assert "[[sessions]]" in result
    assert "[sessions.metadata]" in result


def test_aot_clear_and_repopulate():
    """Test clearing an AoT and repopulating it - mimics _update_from_context pattern."""
    doc = tomlkit.document()

    # Initial population
    sessions = aot()
    session1 = table()
    session1["id"] = 1
    sessions.append(session1)
    doc["sessions"] = sessions

    print("Initial AoT:")
    print(doc.as_string())
    print()

    # Now clear and repopulate - this is what _update_from_context does
    proc_sessions = doc.get("sessions")
    proc_sessions.clear()

    # Add new data
    session2 = table()
    session2["id"] = 2
    session2["name"] = "new session"
    proc_sessions.append(session2)

    result = doc.as_string()
    print("After clear and repopulate:")
    print(result)
    print()

    assert "[[sessions]]" in result
    assert "id = 2" in result


def test_aot_with_item_wrapper():
    """Test using tomlkit.item() wrapper on dict - mimics actual code pattern."""
    doc = tomlkit.document()

    sessions = aot()

    # This mimics the pattern in _update_from_context:
    # to_add = sess.copy()
    # t = tomlkit.item(to_add)
    # proc_sessions.append(t)

    raw_dict = {
        "id": 1,
        "start": "2000-01-01T00:00:00.000",
        "end": "2000-01-01T00:00:00.000",
        "filter": "NonePlaceholder",
        "imagetyp": "bias",
        "object": "NonePlaceholder",
        "telescop": "D3TELE",
        "num_images": 1,
        "exptime_total": 0.001,
    }

    # Convert to tomlkit item
    t = item(raw_dict)
    sessions.append(t)

    doc["sessions"] = sessions

    result = doc.as_string()
    print("AoT with item() wrapper on dict:")
    print(result)
    print()

    assert "[[sessions]]" in result or "sessions = [" in result  # Check what we actually get


def test_aot_with_item_and_append():
    """Test using item() then appending more keys - mimics the masters pattern."""
    doc = tomlkit.document()

    sessions = aot()

    # Start with a dict
    raw_dict = {
        "id": 1,
        "name": "test",
    }

    # Convert to item
    t = item(raw_dict)

    # Now append additional nested structure (like masters in the real code)
    options_out = table()
    masters_out = table()

    array_out = array()
    array_out.add_line("/path/to/master1.fits", comment="score: 100")
    array_out.add_line("/path/to/master2.fits", comment="score: 90")
    array_out.add_line()  # trailing line

    masters_out.append("bias", array_out)
    options_out.append("master", masters_out)

    # This is the critical line - appending to an item created from dict
    t.append("options", options_out)

    sessions.append(t)
    doc["sessions"] = sessions

    result = doc.as_string()
    print("AoT with item() and subsequent append:")
    print(result)
    print()

    # Check if it's valid
    print("Checking validity...")
    try:
        parsed = tomlkit.parse(result)
        print("✓ Valid TOML!")
    except Exception as e:
        print(f"✗ Invalid TOML: {e}")
        raise


def test_full_reproduction():
    """Full reproduction of the ProcessedTarget pattern."""
    doc = tomlkit.document()

    # Set up initial document structure
    doc["repo"] = {"kind": "processed-master"}
    doc["stages"] = {"used": ["master_bias"], "excluded": []}

    # Get or create sessions AoT
    proc_sessions = doc.get("sessions")
    if proc_sessions is None:
        proc_sessions = aot()
        doc["sessions"] = proc_sessions

    # Clear it
    proc_sessions.clear()

    # Simulate session data
    sessions_data = [
        {
            "id": 1,
            "start": "2000-01-01T00:00:00.000",
            "end": "2000-01-01T00:00:00.000",
            "filter": "NonePlaceholder",
            "imagetyp": "bias",
            "object": "NonePlaceholder",
            "telescop": "D3TELE",
            "num_images": 1,
            "exptime_total": 0.001,
            "exptime": 0.001,
            "image_doc_id": 1,
            "repo_url": "file:///test-data/dwarf3",
        }
    ]

    for sess_dict in sessions_data:
        to_add = sess_dict.copy()

        # Convert to tomlkit item
        t = item(to_add)

        # Optionally add nested structure
        # (In real code, this is conditional on whether masters exist)
        metadata = table()
        metadata["SIMPLE"] = True
        metadata["BITPIX"] = 16
        metadata["INSTRUME"] = "TELE"

        t.append("metadata", metadata)

        proc_sessions.append(t)

    result = doc.as_string()
    print("Full reproduction:")
    print(result)
    print()

    # Verify it's valid TOML
    print("Parsing result to verify validity...")
    try:
        parsed = tomlkit.parse(result)
        print("✓ Valid TOML!")
        print(f"Number of sessions: {len(parsed.get('sessions', []))}")
    except Exception as e:
        print(f"✗ Invalid TOML: {e}")
        print("\nProblematic output:")
        print(result)
        raise


def test_item_vs_table():
    """Compare behavior of item() vs table() for AoT elements."""
    doc1 = tomlkit.document()
    doc2 = tomlkit.document()

    # Using table()
    sessions1 = aot()
    t1 = table()
    t1["id"] = 1
    t1["name"] = "test"
    sessions1.append(t1)
    doc1["sessions"] = sessions1

    # Using item() on dict
    sessions2 = aot()
    t2 = item({"id": 1, "name": "test"})
    sessions2.append(t2)
    doc2["sessions"] = sessions2

    result1 = doc1.as_string()
    result2 = doc2.as_string()

    print("Using table():")
    print(result1)
    print()

    print("Using item() on dict:")
    print(result2)
    print()

    # Both should produce valid TOML
    assert "[[sessions]]" in result1
    # But what about result2?


def test_repo_get_with_aot_default():
    """Test Repo.get() behavior with AoT default - potential bug location."""
    from pathlib import Path

    from repo import Repo

    # Create a minimal TOML document
    doc = tomlkit.document()
    doc["repo"] = {"kind": "test"}

    # Simulate what happens in _update_from_context
    # when it calls: self.repo.get("sessions", default=tomlkit.aot(), do_create=True)

    # First, let's see what happens if we just assign an AoT
    sessions = doc.get("sessions")
    if sessions is None:
        sessions = aot()
        doc["sessions"] = sessions

    # Clear and add item
    sessions.clear()
    raw_dict = {"id": 1, "name": "test"}
    t = item(raw_dict)
    sessions.append(t)

    result1 = doc.as_string()
    print("Direct AoT assignment and usage:")
    print(result1)
    print()

    # Now test what Repo.get() does
    # Create a temporary repo to test with
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[repo]\nkind = "test"\n')
        temp_path = f.name

    try:
        repo = Repo(Path(temp_path))

        # This is the pattern used in _update_from_context
        proc_sessions = repo.get("sessions", default=tomlkit.aot(), do_create=True)
        print(f"Type of proc_sessions: {type(proc_sessions)}")
        print(f"Is AoT? {isinstance(proc_sessions, AoT)}")

        proc_sessions.clear()

        raw_dict = {"id": 1, "name": "test"}
        t = item(raw_dict)
        proc_sessions.append(t)

        result2 = repo.config.as_string()
        print("Using Repo.get() with AoT default:")
        print(result2)
        print()

        # Check if it's valid
        try:
            parsed = tomlkit.parse(result2)
            print("✓ Valid TOML!")
        except Exception as e:
            print(f"✗ Invalid TOML: {e}")
            print("\nThe bug is that Repo.get() doesn't properly preserve AoT type!")
            print("It should check isinstance(default, tomlkit.items.AoT) before converting.")
            raise
    finally:
        os.unlink(temp_path)


if __name__ == "__main__":
    import sys

    tests = [
        ("Basic AoT creation", test_basic_aot_creation),
        ("AoT with nested structures", test_aot_with_nested_structures),
        ("AoT clear and repopulate", test_aot_clear_and_repopulate),
        ("AoT with item() wrapper", test_aot_with_item_wrapper),
        ("AoT with item() and append", test_aot_with_item_and_append),
        ("Full reproduction", test_full_reproduction),
        ("item() vs table()", test_item_vs_table),
        ("Repo.get() with AoT default", test_repo_get_with_aot_default),
    ]

    failed = []

    for name, test_func in tests:
        print("=" * 80)
        print(f"Running: {name}")
        print("=" * 80)
        try:
            test_func()
            print(f"✓ {name} passed\n")
        except Exception as e:
            print(f"✗ {name} FAILED: {e}\n")
            failed.append((name, e))
            import traceback

            traceback.print_exc()
            print()

    print("=" * 80)
    print("Summary")
    print("=" * 80)
    print(f"Passed: {len(tests) - len(failed)}/{len(tests)}")
    if failed:
        print(f"Failed: {len(failed)}")
        for name, error in failed:
            print(f"  - {name}: {error}")
        sys.exit(1)
    else:
        print("All tests passed!")
