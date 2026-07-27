"""Content loader (03_CONTENT_SPEC §3): scan the content folders, validate through
the six checks, and build an in-memory library keyed by id.

Invalid files are skipped with a warning (filename + failed check) and the app
keeps running. `refresh()` rebuilds from disk and swaps the library atomically so
in-flight readers always see a complete, self-consistent snapshot (G-6).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.engine.content_models import Benchmarks, Case, Guesstimate, Lesson
from app.engine.validation import Violation, validate_all

log = logging.getLogger(__name__)

_CONTENT = Case | Guesstimate | Lesson


@dataclass(frozen=True)
class ContentLibrary:
    """An immutable snapshot of all valid content, keyed by id."""

    benchmarks: Benchmarks
    cases: dict[str, Case] = field(default_factory=dict)
    guesstimates: dict[str, Guesstimate] = field(default_factory=dict)
    lessons: dict[str, Lesson] = field(default_factory=dict)
    warnings: list[Violation] = field(default_factory=list)

    def get(self, content_id: str) -> _CONTENT | None:
        """Look up any case/guesstimate/lesson by id."""
        return (
            self.cases.get(content_id)
            or self.guesstimates.get(content_id)
            or self.lessons.get(content_id)
        )

    def by_type(self, kind: str) -> dict[str, _CONTENT]:
        """`kind` is 'case' | 'guesstimate' | 'lesson'."""
        return {
            "case": self.cases,
            "guesstimate": self.guesstimates,
            "lesson": self.lessons,
        }[kind]


def _read_json(path: Path) -> tuple[dict | None, Violation | None]:
    try:
        return json.loads(path.read_text()), None
    except (OSError, json.JSONDecodeError) as e:
        return None, Violation(str(path), "json", str(e))


class ContentLoader:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._library = self._build()

    @property
    def library(self) -> ContentLibrary:
        return self._library

    def refresh(self) -> ContentLibrary:
        """Rebuild from disk and swap atomically."""
        self._library = self._build()
        return self._library

    def _build(self) -> ContentLibrary:
        read_errors: list[Violation] = []

        bpath = self.root / "benchmarks.json"
        braw, err = _read_json(bpath) if bpath.exists() else (None, None)
        if err:
            read_errors.append(err)
        benchmarks_raw = (str(bpath), braw or {})

        def load_dir(sub: str) -> list[tuple[str, dict]]:
            out: list[tuple[str, dict]] = []
            for p in sorted((self.root / sub).glob("*.json")):
                raw, err = _read_json(p)
                if err:
                    read_errors.append(err)
                elif isinstance(raw, dict):
                    out.append((str(p), raw))
                else:
                    read_errors.append(
                        Violation(str(p), "schema", "top level is not an object")
                    )
            return out

        result = validate_all(
            benchmarks_raw,
            load_dir("cases"),
            load_dir("guesstimates"),
            load_dir("lessons"),
        )

        warnings = read_errors + result.violations
        for w in warnings:
            log.warning("skipping %s: [%s] %s", Path(w.file).name, w.check, w.detail)

        return ContentLibrary(
            benchmarks=result.benchmarks,
            cases={c.meta.id: c for c in result.cases.values()},
            guesstimates={g.meta.id: g for g in result.guesstimates.values()},
            lessons={lsn.meta.id: lsn for lsn in result.lessons.values()},
            warnings=warnings,
        )
