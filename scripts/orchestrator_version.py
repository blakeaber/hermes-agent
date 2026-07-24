"""
orchestrator_version.py

Utility for reading and comparing the orchestrator version from a VERSION file.
"""

from pathlib import Path


VERSION_FILE = Path(__file__).parent.parent / "VERSION"


def read_version(path: Path = VERSION_FILE) -> str:
    """Read and return the version string from the given file, stripped of whitespace."""
    return path.read_text(encoding="utf-8").strip()


def is_version_at_least(minimum: str, path: Path = VERSION_FILE) -> bool:
    """Return True if the version in the file is >= minimum (semver-style comparison)."""
    current = read_version(path)
    return _parse_version(current) >= _parse_version(minimum)


def _parse_version(version: str) -> tuple:
    """Parse a version string like '1.2.3' into a tuple of ints for comparison."""
    parts = version.lstrip("v").split(".")
    result = []
    for part in parts:
        # Only take leading digits to handle pre-release suffixes like '1.2.3-alpha'
        numeric = ""
        for ch in part:
            if ch.isdigit():
                numeric += ch
            else:
                break
        result.append(int(numeric) if numeric else 0)
    return tuple(result)
