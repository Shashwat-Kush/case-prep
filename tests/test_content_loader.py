import json
import shutil
from pathlib import Path

import pytest

from app.engine.content_loader import ContentLoader

VALID = Path(__file__).parent / "fixtures" / "content" / "valid"


@pytest.fixture
def content_dir(tmp_path: Path) -> Path:
    """A writable copy of the valid fixture set."""
    shutil.copytree(VALID, tmp_path, dirs_exist_ok=True)
    return tmp_path


def test_loads_valid_set(content_dir: Path):
    lib = ContentLoader(content_dir).library
    assert lib.warnings == []
    assert "case-cement-profitability" in lib.cases
    assert "guess-petrol-pumps-delhi" in lib.guesstimates
    assert "lesson-profitability" in lib.lessons
    assert "india_population" in lib.benchmarks


def test_lookup_by_id_and_type(content_dir: Path):
    lib = ContentLoader(content_dir).library
    assert (
        lib.get("case-cement-profitability") is lib.cases["case-cement-profitability"]
    )
    assert lib.get("nope") is None
    assert lib.by_type("guesstimate") is lib.guesstimates


def test_invalid_file_skipped_with_warning(content_dir: Path):
    bad = content_dir / "cases" / "case-broken.json"
    bad.write_text(
        json.dumps({"meta": {"id": "case-broken"}})
    )  # missing required fields
    lib = ContentLoader(content_dir).library
    assert "case-broken" not in {c.meta.id for c in lib.cases.values()}
    assert any(
        Path(w.file).name == "case-broken.json" and w.check == "schema"
        for w in lib.warnings
    )
    assert "case-cement-profitability" in lib.cases  # valid siblings still load


def test_malformed_json_reported(content_dir: Path):
    (content_dir / "cases" / "case-garbage.json").write_text("{not json")
    lib = ContentLoader(content_dir).library
    assert any(
        w.check == "json" and Path(w.file).name == "case-garbage.json"
        for w in lib.warnings
    )


def test_refresh_picks_up_added_and_removed(content_dir: Path):
    loader = ContentLoader(content_dir)
    assert "guess-petrol-pumps-delhi" in loader.library.guesstimates

    added = content_dir / "guesstimates" / "guess-new.json"
    src = json.loads(
        (content_dir / "guesstimates" / "guess-petrol-pumps-delhi.json").read_text()
    )
    src["meta"]["id"] = "guess-new"
    added.write_text(json.dumps(src))

    loader.refresh()
    assert "guess-new" in loader.library.guesstimates

    added.unlink()
    (content_dir / "guesstimates" / "guess-petrol-pumps-delhi.json").unlink()
    loader.refresh()
    assert "guess-new" not in loader.library.guesstimates
    assert "guess-petrol-pumps-delhi" not in loader.library.guesstimates


def test_refresh_swaps_atomically(content_dir: Path):
    loader = ContentLoader(content_dir)
    first = loader.library
    second = loader.refresh()
    assert first is not second  # new snapshot object
    assert loader.library is second
