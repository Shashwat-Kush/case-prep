import json
import shutil
from pathlib import Path

from scripts.validate_case import main

VALID = Path(__file__).parent / "fixtures" / "content" / "valid"


def test_valid_dir_exits_zero(capsys):
    assert main(["validate_case.py", str(VALID)]) == 0
    assert "OK:" in capsys.readouterr().out


def test_invalid_dir_exits_nonzero(tmp_path: Path, capsys):
    shutil.copytree(VALID, tmp_path, dirs_exist_ok=True)
    (tmp_path / "cases" / "case-broken.json").write_text(
        json.dumps({"meta": {"id": "case-broken"}})
    )
    assert main(["validate_case.py", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "case-broken.json" in out
    assert "violation(s)" in out
