"""Unit tests for the Starbash doit module."""

import io
import sys
from contextlib import redirect_stdout

import pytest

from starbash.doit import StarbashDoit, cleanup_temporaries, my_builtin_task


class TestStarbashDoit:
    """Tests for the StarbashDoit class."""

    def test_init(self):
        """Test that StarbashDoit can be instantiated."""
        doit = StarbashDoit()
        assert doit is not None

    def test_setup(self):
        """Test that setup method exists and can be called."""
        doit = StarbashDoit()
        # Should not raise any errors
        doit.setup({})

    def test_load_doit_config(self):
        """Test that load_doit_config returns expected config."""
        doit = StarbashDoit()
        config = doit.load_doit_config()
        assert isinstance(config, dict)
        assert "verbosity" in config
        assert config["verbosity"] == 2
        # Should also include dep_file to store DB in cache directory
        assert "dep_file" in config
        assert "doit.json" in config["dep_file"]

    def test_load_tasks(self):
        """Test that load_tasks returns a list of tasks."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        task_list = doit.load_tasks(None, [])
        assert isinstance(task_list, list)
        assert len(task_list) == 1
        # The task should have the expected attributes
        task = task_list[0]
        assert task.name == "sample_task"
        assert task.doc == "sample doc"

    def test_run_list_command(self, capsys):
        """Test that run method works with the 'list' command."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        result = doit.run(["list"])

        # Check that it ran successfully (exit code 0)
        assert result == 0

        # Capture output and verify our sample task is listed
        captured = capsys.readouterr()
        assert "sample_task" in captured.out

    def test_run_help_command(self, capsys):
        """Test that run method works with the 'help' command."""
        doit = StarbashDoit()
        result = doit.run(["help"])

        # Help command should succeed
        assert result == 0

        # Capture output and verify help was shown
        captured = capsys.readouterr()
        assert "help" in captured.out.lower() or "usage" in captured.out.lower()

    @pytest.mark.slow
    def test_run_sample_task(self, capfd):
        """Test that run method can execute the sample task."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        result = doit.run(["sample_task"])

        # Task should execute successfully
        assert result == 0

        # Capture output and verify the echo command ran
        # Use capfd (file descriptor capture) instead of capsys because doit writes directly to stdout
        captured = capfd.readouterr()
        assert "hello from built in" in captured.out

    def test_run_list_with_status(self, capsys):
        """Test that run method works with list options."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        result = doit.run(["list", "--status"])

        # Should run successfully
        assert result == 0

        captured = capsys.readouterr()
        assert "sample_task" in captured.out


class TestBuiltinTask:
    """Tests for the built-in task definition."""

    def test_builtin_task_structure(self):
        """Test that my_builtin_task has the expected structure."""
        assert isinstance(my_builtin_task, dict)
        assert "name" in my_builtin_task
        assert "actions" in my_builtin_task
        assert "doc" in my_builtin_task

    def test_builtin_task_values(self):
        """Test that my_builtin_task has the expected values."""
        assert my_builtin_task["name"] == "sample_task"
        assert my_builtin_task["actions"] == ["echo hello from built in"]
        assert my_builtin_task["doc"] == "sample doc"

    def test_builtin_task_actions_is_list(self):
        """Test that actions is a list."""
        assert isinstance(my_builtin_task["actions"], list)
        assert len(my_builtin_task["actions"]) == 1


class TestCleanupTemporaries:
    """Tests for cleanup_temporaries()."""

    def _make_tree(self, base):
        """Create a representative set of files/dirs in ``base``."""
        (base / "in.seq").write_text("seq")
        seq_dir = base / "in"
        seq_dir.mkdir()
        (seq_dir / "in_0001.fits").write_text("data")
        (base / "r_in.seq").write_text("seq")
        (base / "r_in_0001.fits").write_text("data")
        (base / "stacked.fits").write_text("result")  # must be preserved

    def test_removes_matching_files_and_dirs(self, tmp_path):
        self._make_tree(tmp_path)
        stage = {"temporaries": ["in*", "r_in*"]}
        context = {"process_dir": str(tmp_path)}

        cleanup_temporaries(stage, context)

        assert not (tmp_path / "in.seq").exists()
        assert not (tmp_path / "in").exists()
        assert not (tmp_path / "r_in.seq").exists()
        assert not (tmp_path / "r_in_0001.fits").exists()
        # Non-matching output file is preserved.
        assert (tmp_path / "stacked.fits").exists()

    def test_expands_context_variables(self, tmp_path):
        (tmp_path / "pp_light_s23.seq").write_text("seq")
        (tmp_path / "keep.fits").write_text("keep")
        stage = {"temporaries": ["pp_{light_base}*"]}
        context = {"process_dir": str(tmp_path), "light_base": "light_s23"}

        cleanup_temporaries(stage, context)

        assert not (tmp_path / "pp_light_s23.seq").exists()
        assert (tmp_path / "keep.fits").exists()

    def test_empty_or_missing_temporaries_is_noop(self, tmp_path):
        (tmp_path / "keep.fits").write_text("keep")
        cleanup_temporaries({"temporaries": []}, {"process_dir": str(tmp_path)})
        cleanup_temporaries({}, {"process_dir": str(tmp_path)})
        cleanup_temporaries(None, {"process_dir": str(tmp_path)})
        assert (tmp_path / "keep.fits").exists()

    def test_unsafe_patterns_are_skipped(self, tmp_path):
        outside = tmp_path.parent / "outside.fits"
        outside.write_text("do not delete")
        try:
            stage = {"temporaries": ["../outside.fits", "/etc/passwd", "sub/foo*"]}
            cleanup_temporaries(stage, {"process_dir": str(tmp_path)})
            assert outside.exists()
        finally:
            outside.unlink(missing_ok=True)



class TestDoitIntegration:
    """Integration tests running actual doit commands."""

    def test_run_without_args_shows_help(self, capfd):
        """Test that running without args shows help/usage."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        result = doit.run([])

        # Should succeed or fail gracefully
        assert result in [0, 2, 3]  # Various help exit codes

        # Use capfd (file descriptor capture) instead of capsys because doit writes directly to stdout
        captured = capfd.readouterr()
        # Should show some usage information
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_run_info_command(self, capsys):
        """Test the 'info' command."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        result = doit.run(["info", "sample_task"])

        # Info command returns 1 but still displays info
        assert result in [0, 1]

        captured = capsys.readouterr()
        # Should show info about the task
        assert "sample_task" in captured.out
        assert "sample doc" in captured.out

    def test_list_shows_all_tasks(self, capsys):
        """Test that list command shows all available tasks."""
        doit = StarbashDoit()
        # Manually add the sample task since it's no longer auto-populated
        doit.add_task(my_builtin_task)
        result = doit.run(["list"])

        assert result == 0
        captured = capsys.readouterr()

        # Should show our sample task
        assert "sample_task" in captured.out
        # Should show the doc string
        assert "sample doc" in captured.out

    def test_run_nonexistent_task(self, capsys):
        """Test that running a nonexistent task fails gracefully."""
        doit = StarbashDoit()
        result = doit.run(["nonexistent_task"])

        # Should fail with exit code 3 (task not found)
        assert result == 3

        captured = capsys.readouterr()
        # Should show an error message
        assert len(captured.err) > 0
