#!/usr/bin/env python3
"""Print the next patch version from semantic version tags read on stdin."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable

VERSION_TAG = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def next_patch_version(tags: Iterable[str]) -> str:
    versions = []
    for tag in tags:
        match = VERSION_TAG.fullmatch(tag.strip())
        if match:
            versions.append(tuple(int(part) for part in match.groups()))

    if not versions:
        return "0.1.0"

    major, minor, patch = max(versions)
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    print(next_patch_version(sys.stdin))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
