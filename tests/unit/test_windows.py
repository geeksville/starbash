"""Tests for Windows-specific utilities."""

import os
from unittest.mock import patch

from starbash.windows import is_under_powershell


class TestIsUnderPowershell:
    """Tests for is_under_powershell detection."""

    def test_returns_true_when_psmodulepath_present(self):
        """Should return True when PSModulePath environment variable is set."""
        with patch.dict(os.environ, {"PSModulePath": "C:\\Program Files\\PowerShell\\Modules"}):
            assert is_under_powershell() is True

    def test_returns_false_when_psmodulepath_absent(self):
        """Should return False when PSModulePath environment variable is not set."""
        # Explicitly patch with empty dict, ensuring PSModulePath is not present
        with patch.dict(os.environ, {}, clear=True):
            assert is_under_powershell() is False

    def test_returns_true_with_multiple_ps_env_vars(self):
        """Should return True when multiple PowerShell environment variables are present."""
        with patch.dict(
            os.environ,
            {
                "PSModulePath": "C:\\Program Files\\PowerShell\\Modules",
                "PSEdition": "Core",
                "POWERSHELL_DISTRIBUTION_CHANNEL": "MSI:Windows 10",
            },
        ):
            assert is_under_powershell() is True

    def test_returns_false_with_non_ps_env_vars(self):
        """Should return False when only non-PowerShell environment variables are present."""
        # Set only cmd.exe vars, explicitly excluding any PS variables
        env = {
            "PATH": "C:\\Windows\\System32",
            "COMSPEC": "C:\\Windows\\System32\\cmd.exe",
            "PROMPT": "$P$G",
        }
        with patch.dict(os.environ, env, clear=True):
            assert is_under_powershell() is False
