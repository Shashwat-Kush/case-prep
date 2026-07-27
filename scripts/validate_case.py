#!/usr/bin/env python3
"""Validate all content under a root dir (default: repo root) through the six
checks (T-011), reusing the content loader's scan (T-013). Lists every violation
grouped by file and exits nonzero if any. Run standalone or from the pre-commit
hook:

    python scripts/validate_case.py [root]
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.content_loader import ContentLoader  # noqa: E402


def main(argv: list[str]) -> int:
    # The loader logs skips; the CLI prints them itself, so keep it quiet.
    logging.getLogger("app.engine.content_loader").setLevel(logging.ERROR)

    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    lib = ContentLoader(root).library

    if not lib.warnings:
        n = len(lib.cases) + len(lib.guesstimates) + len(lib.lessons)
        b = len(list(lib.benchmarks.keys()))
        print(f"OK: {n} content files valid, {b} benchmarks")
        return 0

    by_file: dict[str, list] = defaultdict(list)
    for v in lib.warnings:
        by_file[v.file].append(v)
    for f in sorted(by_file):
        print(
            f"FAIL {Path(f).relative_to(root) if Path(f).is_relative_to(root) else f}"
        )
        for v in by_file[f]:
            detail = v.detail.strip().replace("\n", "\n      ")
            print(f"  [{v.check}] {detail}")
    print(f"\n{len(lib.warnings)} violation(s)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
