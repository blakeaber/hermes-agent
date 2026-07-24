"""
orchestrator_version.py

Utility for printing version information in JSON format.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone


def get_git_sha() -> str:
    """Return the current Git SHA."""
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()


def get_python_version() -> str:
    """Return the current Python version."""
    return sys.version.split()[0]


def get_utc_time() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    """Print version information in JSON format."""
    version_info = {
        "git_sha": get_git_sha(),
        "python_version": get_python_version(),
        "utc_time": get_utc_time(),
    }
    print(json.dumps(version_info))


if __name__ == "__main__":
    main()
