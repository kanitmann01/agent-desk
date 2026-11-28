"""The deck tools from a terminal, with no model endpoint and no browser.

The CLI is the same surface a plugin declares, so an agent can drive it
with one command per step and read JSON back.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.presentations.cli import main


def _printed(capsys):
    return json.loads(capsys.readouterr().out)


def test_list_prints_the_installed_template(capsys):
    assert main(["list"]) == 0
    result = _printed(capsys)
    assert [row["id"] for row in result["templates"]] == ["starter"]
    assert "qbr" in result["templates"][0]["recipes"]
    assert result["templates"][0]["tools"] == [
        "presentation_outline", "presentation_create",
        "presentation_inspect", "presentation_render",
    ]


def test_outline_prints_slides(capsys):
    assert main(["outline", "--brief", "the Q3 business review"]) == 0
    result = _printed(capsys)
    assert result["outline"]["title"] == "the Q3 business review"
    assert len(result["outline"]["slides"]) >= 3


def test_create_then_inspect_a_deck(tmp_path, capsys):
    out = tmp_path / "q3.pptx"
    assert main([
        "create", "--brief", "the Q3 business review", "--out", str(out),
    ]) == 0
    created = _printed(capsys)
    assert Path(created["file"]) == out.resolve()
    assert out.is_file()
    assert created["slides"] >= 3

    assert main(["inspect", str(out)]) == 0
    seen = _printed(capsys)
    assert seen["ok"] is True
    assert len(seen["slides"]) == created["slides"]


def test_create_with_no_brief_or_outline_is_exit_2(tmp_path, capsys):
    code = main(["create", "--out", str(tmp_path / "empty.pptx")])
    assert code == 2
    assert "brief" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "empty.pptx").exists()


def test_a_missing_deck_is_exit_2(tmp_path, capsys):
    code = main(["inspect", str(tmp_path / "nope.pptx")])
    assert code == 2
    assert "not found" in json.loads(capsys.readouterr().err)["error"]
