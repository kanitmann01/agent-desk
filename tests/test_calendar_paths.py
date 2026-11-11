"""Calendar path resolution: candidates, reader precedence, hint honesty.

The watcher and the walkthrough hint must agree on where the synced file
lives, so these tests monkeypatch Path.home into a tmp home and check
both sides over the same shapes: the plain OneDrive folder, the
'OneDrive - Company' glob, the macOS CloudStorage mount, and the env
override that beats them all.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.calendar.watcher import default_calendar_candidates, default_read_calendar
from agentdesk.server.app import default_calendar_hint


def fake_home(monkeypatch, tmp_path) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("AGENTDESK_CALENDAR_FILE", raising=False)
    return tmp_path


def plant(home: Path, shape: str) -> Path:
    """Create the calendar file under a given home shape, return its path."""
    target = home / shape / "agent-desk" / "calendar_sync.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}")
    return target


class TestCandidates:
    def test_env_override_beats_every_default(self, monkeypatch, tmp_path):
        fake_home(monkeypatch, tmp_path)
        override = tmp_path / "elsewhere" / "calendar_sync.json"
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", str(override))
        plant(tmp_path, "OneDrive")  # a real file in the default place exists

        # The override is exclusive: defaults are not even listed, and the
        # reader answers nothing rather than falling back behind its back.
        assert default_calendar_candidates() == [override]
        assert default_read_calendar() is None

    def test_env_override_is_read_once_it_exists(self, monkeypatch, tmp_path):
        fake_home(monkeypatch, tmp_path)
        override = tmp_path / "elsewhere" / "calendar_sync.json"
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", str(override))
        override.parent.mkdir(parents=True)
        override.write_bytes(b"{}")

        found = default_read_calendar()
        assert found is not None
        assert Path(found[0]) == override

    def test_plain_onedrive_folder_is_the_first_default(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        target = plant(home, "OneDrive")

        candidates = default_calendar_candidates()
        assert candidates[0] == target
        found = default_read_calendar()
        assert found is not None
        assert Path(found[0]) == target

    def test_company_onedrive_glob_shape_is_accepted(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        target = plant(home, "OneDrive - Contoso")

        found = default_read_calendar()
        assert found is not None
        assert Path(found[0]) == target

    def test_macos_cloudstorage_shape_is_accepted(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        target = plant(home, "Library/CloudStorage/OneDrive-Contoso")

        candidates = default_calendar_candidates()
        assert target in candidates
        # After the Windows shapes: order stays stable across platforms.
        assert candidates.index(target) > 0
        found = default_read_calendar()
        assert found is not None
        assert Path(found[0]) == target

    def test_glob_hits_are_sorted_so_order_is_deterministic(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        alpha = plant(home, "OneDrive-Alpha")
        beta = plant(home, "OneDrive-Beta")

        candidates = default_calendar_candidates()
        assert candidates.index(alpha) < candidates.index(beta)


class TestHint:
    def test_shows_the_first_candidate_that_exists(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        # Only the CloudStorage shape exists: the hint must point there,
        # not at the plain OneDrive folder the reader would ignore.
        target = plant(home, "Library/CloudStorage/OneDrive-Contoso")

        assert default_calendar_hint() == target

    def test_falls_back_to_the_first_default_when_nothing_exists(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)

        assert default_calendar_hint() == home / "OneDrive" / "agent-desk" / "calendar_sync.json"

    def test_shows_the_env_override_even_before_it_exists(self, monkeypatch, tmp_path):
        fake_home(monkeypatch, tmp_path)
        override = tmp_path / "custom" / "calendar_sync.json"
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", str(override))

        assert default_calendar_hint() == override
