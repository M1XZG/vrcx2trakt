from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "next_patch_version.py"


def run_version_script(*tags: str) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="\n".join(tags),
        capture_output=True,
        check=True,
        text=True,
    )
    return result.stdout.strip()


def test_increments_latest_patch_version():
    assert run_version_script("v1.0.0", "v1.1.0") == "1.1.1"


def test_uses_highest_semantic_version_regardless_of_input_order():
    assert run_version_script("v2.0.3", "v1.20.9", "v2.0.1") == "2.0.4"


def test_ignores_non_semantic_tags():
    assert run_version_script("v1.2.3-beta", "version-4", "v1.2.3") == "1.2.4"


def test_starts_at_zero_one_zero_without_release_tags():
    assert run_version_script() == "0.1.0"
