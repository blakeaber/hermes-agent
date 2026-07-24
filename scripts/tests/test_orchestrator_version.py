"""
Tests for orchestrator_version.py
"""

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open

import sys
import os

# Ensure the scripts directory is on the path so we can import orchestrator_version
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator_version import read_version, is_version_at_least, _parse_version


class TestParseVersion:
    def test_simple_version(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_version_with_v_prefix(self):
        assert _parse_version("v2.0.0") == (2, 0, 0)

    def test_single_component(self):
        assert _parse_version("5") == (5,)

    def test_two_components(self):
        assert _parse_version("3.7") == (3, 7)

    def test_version_with_prerelease_suffix(self):
        # Only numeric leading part of each segment is used
        assert _parse_version("1.2.3-alpha") == (1, 2, 3)

    def test_zero_version(self):
        assert _parse_version("0.0.0") == (0, 0, 0)


class TestReadVersion:
    def test_reads_and_strips_version(self, tmp_path):
        version_file = tmp_path / "VERSION"
        version_file.write_text("  1.4.2\n", encoding="utf-8")
        assert read_version(version_file) == "1.4.2"

    def test_reads_plain_version(self, tmp_path):
        version_file = tmp_path / "VERSION"
        version_file.write_text("2.0.0", encoding="utf-8")
        assert read_version(version_file) == "2.0.0"

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "MISSING"
        with pytest.raises(FileNotFoundError):
            read_version(missing)


class TestIsVersionAtLeast:
    def _make_version_file(self, tmp_path, version: str) -> Path:
        f = tmp_path / "VERSION"
        f.write_text(version, encoding="utf-8")
        return f

    def test_equal_version_returns_true(self, tmp_path):
        vf = self._make_version_file(tmp_path, "1.2.3")
        assert is_version_at_least("1.2.3", path=vf) is True

    def test_greater_version_returns_true(self, tmp_path):
        vf = self._make_version_file(tmp_path, "2.0.0")
        assert is_version_at_least("1.9.9", path=vf) is True

    def test_lesser_version_returns_false(self, tmp_path):
        vf = self._make_version_file(tmp_path, "1.0.0")
        assert is_version_at_least("1.0.1", path=vf) is False

    def test_patch_version_comparison(self, tmp_path):
        vf = self._make_version_file(tmp_path, "1.2.5")
        assert is_version_at_least("1.2.3", path=vf) is True

    def test_minor_version_comparison(self, tmp_path):
        vf = self._make_version_file(tmp_path, "1.3.0")
        assert is_version_at_least("1.4.0", path=vf) is False

    def test_version_with_v_prefix_in_file(self, tmp_path):
        vf = self._make_version_file(tmp_path, "v3.1.0")
        assert is_version_at_least("3.0.0", path=vf) is True

    def test_version_with_whitespace_in_file(self, tmp_path):
        vf = self._make_version_file(tmp_path, "  1.5.0\n")
        assert is_version_at_least("1.5.0", path=vf) is True
