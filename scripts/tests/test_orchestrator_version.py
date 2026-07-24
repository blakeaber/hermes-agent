"""
Tests for orchestrator_version.py
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from io import StringIO
from datetime import datetime, timezone

import sys
from pathlib import Path

# Ensure the scripts directory is on the path so we can import orchestrator_version
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator_version import get_git_sha, get_python_version, get_utc_time, main


class TestGetGitSha:
    @patch("subprocess.check_output")
    def test_get_git_sha(self, mock_check_output):
        mock_check_output.return_value = b"1234567890abcdef\n"
        assert get_git_sha() == "1234567890abcdef"


class TestGetPythonVersion:
    def test_get_python_version(self):
        # Just check it doesn't crash and returns something plausible
        version = get_python_version()
        assert isinstance(version, str)
        assert "." in version


class TestGetUtcTime:
    def test_get_utc_time(self):
        # Check it's a valid ISO 8601 UTC datetime
        utc_time = get_utc_time()
        dt = datetime.fromisoformat(utc_time)
        assert dt.tzinfo == timezone.utc


class TestMain:
    @patch("orchestrator_version.get_git_sha", return_value="1234567890abcdef")
    @patch("orchestrator_version.get_python_version", return_value="3.9.5")
    @patch("orchestrator_version.get_utc_time", return_value="2023-04-01T12:00:00+00:00")
    @patch("sys.stdout", new_callable=StringIO)
    def test_main_output(self, mock_stdout, mock_utc_time, mock_python_version, mock_git_sha):
        main()
        output = json.loads(mock_stdout.getvalue())
        assert output == {
            "git_sha": "1234567890abcdef",
            "python_version": "3.9.5",
            "utc_time": "2023-04-01T12:00:00+00:00",
        }
