"""Shared content validation (03_CONTENT_SPEC §4): the six checks, run both by the
CLI validator (T-012) and the content loader (T-013).

Violations are returned as structured data, never raised, so callers can
skip-with-warning (03_CONTENT_SPEC §3). Recompute/reference conventions are
recorded in docs/decisions.md.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.engine.content_models import (
    BENCHMARK_KEY,
    Benchmarks,
    Case,
    Guesstimate,
    Lesson,
)


@dataclass(frozen=True)
class Violation:
    file: str
    check: str
    detail: str


# --- Safe arithmetic evaluator (checks 2 and 3) ------------------------------

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


class MathExprError(Exception):
    pass


def safe_eval(expr: str, names: dict[str, float]) -> float:
    """Evaluate an arithmetic expression over `names`. Arithmetic only: no calls,
    attributes, or names outside `names`."""
    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError as e:
        raise MathExprError(f"cannot parse {expr!r}: {e}") from e
    return _eval_node(node, names)


def _eval_node(node: ast.AST, names: dict[str, float]) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise MathExprError(f"unknown name {node.id!r}")
        return float(names[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](
            _eval_node(node.left, names), _eval_node(node.right, names)
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, names)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd):
        return _eval_node(node.operand, names)
    raise MathExprError(f"disallowed expression element: {ast.dump(node)}")


# --- Per-type validation -----------------------------------------------------


def _schema(model, path: str, raw: dict, check: str = "schema"):
    try:
        return model.model_validate(raw), []
    except ValidationError as e:
        return None, [Violation(path, check, str(e))]


def validate_benchmarks(
    path: str, raw: dict
) -> tuple[Benchmarks | None, list[Violation]]:
    obj, errs = _schema(Benchmarks, path, raw)
    if obj is None:
        return None, errs
    bad = [k for k in obj.keys() if not re.match(BENCHMARK_KEY, k)]
    errs += [
        Violation(path, "schema", f"benchmark key not snake_case: {k}") for k in bad
    ]
    return (obj if not errs else None), errs


def validate_case(
    path: str, raw: dict, benchmarks: Benchmarks, lesson_ids: set[str]
) -> tuple[Case | None, list[Violation]]:
    case, errs = _schema(Case, path, raw)
    if case is None:
        return None, errs

    for i, cp in enumerate(case.math_checkpoints):
        try:
            got = safe_eval(cp.inputs, {})
        except MathExprError as e:
            errs.append(Violation(path, "math_checkpoint", f"checkpoint[{i}]: {e}"))
            continue
        if abs(got - cp.expected_value) > cp.tolerance:
            errs.append(
                Violation(
                    path,
                    "math_checkpoint",
                    f"checkpoint[{i}] {cp.inputs} = {got}, expected "
                    f"{cp.expected_value} +/- {cp.tolerance}",
                )
            )

    phase_names = {p.name for p in case.phases}
    for concept in case.meta.prerequisite_concepts:
        if concept not in lesson_ids:
            errs.append(
                Violation(
                    path,
                    "reference",
                    f"prerequisite_concepts lesson id not found: {concept}",
                )
            )
    for cb in case.curveballs:
        if cb.trigger_phase not in phase_names:
            errs.append(
                Violation(
                    path,
                    "reference",
                    f"curveball.trigger_phase not a phase: {cb.trigger_phase}",
                )
            )
    seen_ex: set[str] = set()
    for ex in case.exhibits:
        if ex.id in seen_ex:
            errs.append(Violation(path, "reference", f"duplicate exhibit id: {ex.id}"))
        seen_ex.add(ex.id)
        if ex.unlock_condition.startswith("phase:"):
            ref = ex.unlock_condition.removeprefix("phase:").strip()
            if ref not in phase_names:
                errs.append(
                    Violation(
                        path,
                        "reference",
                        f"exhibit {ex.id} unlocks on unknown phase: {ref}",
                    )
                )
    return (case if not errs else None), errs


def validate_guesstimate(
    path: str, raw: dict, benchmarks: Benchmarks
) -> tuple[Guesstimate | None, list[Violation]]:
    guess, errs = _schema(Guesstimate, path, raw)
    if guess is None:
        return None, errs

    names: dict[str, float] = {}
    for i, seg in enumerate(guess.approach.tree):
        for ref in seg.benchmark_refs:
            if ref in benchmarks:
                names[ref] = benchmarks[ref].value
            else:
                errs.append(
                    Violation(
                        path,
                        "benchmark_ref",
                        f"segment[{i}] refs missing benchmark: {ref}",
                    )
                )
        if seg.derivation.strip() != "given":
            try:
                got = safe_eval(seg.derivation, names)
            except MathExprError as e:
                errs.append(Violation(path, "guesstimate_tree", f"segment[{i}]: {e}"))
            else:
                if abs(got - seg.value) > seg.tolerance:
                    errs.append(
                        Violation(
                            path,
                            "guesstimate_tree",
                            f"segment[{i}] '{seg.segment}' {seg.derivation} = {got}, "
                            f"stated {seg.value} +/- {seg.tolerance}",
                        )
                    )
        names[seg.segment] = seg.value

    if guess.approach.tree:
        final = guess.approach.tree[-1].value
        r = guess.answer_range
        if not (r.low <= final <= r.high):
            errs.append(
                Violation(
                    path,
                    "guesstimate_tree",
                    f"final estimate {final} outside answer_range [{r.low}, {r.high}]",
                )
            )
    return (guess if not errs else None), errs


def validate_lesson(path: str, raw: dict) -> tuple[Lesson | None, list[Violation]]:
    return _schema(Lesson, path, raw)


# --- Whole-set validation (adds cross-file id uniqueness) --------------------


@dataclass
class ValidationResult:
    benchmarks: Benchmarks
    cases: dict[str, Case]
    guesstimates: dict[str, Guesstimate]
    lessons: dict[str, Lesson]
    violations: list[Violation]


def validate_all(
    benchmarks_raw: tuple[str, dict],
    cases_raw: list[tuple[str, dict]],
    guesstimates_raw: list[tuple[str, dict]],
    lessons_raw: list[tuple[str, dict]],
) -> ValidationResult:
    """Validate an entire content set. Files with any violation are excluded from
    the returned collections; every violation is reported."""
    violations: list[Violation] = []

    bpath, braw = benchmarks_raw
    benchmarks, berrs = validate_benchmarks(bpath, braw)
    violations += berrs
    if benchmarks is None:
        benchmarks = Benchmarks({})

    lessons: dict[str, Lesson] = {}
    for path, raw in lessons_raw:
        obj, errs = validate_lesson(path, raw)
        violations += errs
        if obj is not None:
            lessons[path] = obj
    lesson_ids = {lsn.meta.id for lsn in lessons.values()}

    cases: dict[str, Case] = {}
    for path, raw in cases_raw:
        obj, errs = validate_case(path, raw, benchmarks, lesson_ids)
        violations += errs
        if obj is not None:
            cases[path] = obj

    guesstimates: dict[str, Guesstimate] = {}
    for path, raw in guesstimates_raw:
        obj, errs = validate_guesstimate(path, raw, benchmarks)
        violations += errs
        if obj is not None:
            guesstimates[path] = obj

    _check_unique_ids(cases, guesstimates, lessons, violations)
    return ValidationResult(benchmarks, cases, guesstimates, lessons, violations)


def _check_unique_ids(
    cases, guesstimates, lessons, violations: list[Violation]
) -> None:
    by_id: dict[str, list[str]] = {}
    for coll in (cases, guesstimates, lessons):
        for path, obj in coll.items():
            by_id.setdefault(obj.meta.id, []).append(path)
    dupes = {cid: paths for cid, paths in by_id.items() if len(paths) > 1}
    for cid, paths in dupes.items():
        for path in paths:
            violations.append(
                Violation(
                    path,
                    "duplicate_id",
                    f"id {cid!r} also used by {sorted(set(paths) - {path})}",
                )
            )
    for coll in (cases, guesstimates, lessons):
        for path in [p for p, o in coll.items() if o.meta.id in dupes]:
            del coll[path]
