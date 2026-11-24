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

from agentdesk.calendar.store import (
    clear_calendar_path,
    get_calendar_path,
    set_calendar_path,
)
from agentdesk.calendar.watcher import (
    Adapters,
    CalendarBridge,
    default_calendar_candidates,
    default_read_calendar,
)
import server_harness
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

    def test_an_empty_override_means_no_calendar(self, monkeypatch, tmp_path):
        fake_home(monkeypatch, tmp_path)
        plant(tmp_path, "OneDrive")  # a real file in the default place exists
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", "")

        # A demo or test pins the variable empty to boot a desk that sees
        # no calendar even on a machine that syncs one.
        assert default_calendar_candidates() == []
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

    def test_an_empty_pin_still_names_the_plain_default(self, monkeypatch, tmp_path):
        # The empty pin is the documented way to boot a desk that reads
        # no calendar. The reader answers nothing, but the walkthrough
        # still needs a path to show, so the hint falls back to the
        # plain OneDrive default instead of raising.
        home = fake_home(monkeypatch, tmp_path)
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", "")

        assert default_calendar_hint() == home / "OneDrive" / "agent-desk" / "calendar_sync.json"

    def test_shows_the_env_override_even_before_it_exists(self, monkeypatch, tmp_path):
        fake_home(monkeypatch, tmp_path)
        override = tmp_path / "custom" / "calendar_sync.json"
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", str(override))

        assert default_calendar_hint() == override


class TestExplicitPathPrecedence:
    """The stored explicit choice outranks env, which outranks candidates.

    The bridge polls through the same precedence, so what the source
    page shows is what every poll reads.
    """

    def make_bridge(self, tmp_path):
        import sqlite3

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        adapters = Adapters(read_calendar=default_read_calendar, clock=lambda: 1_700_000_000.0)
        return CalendarBridge(conn, adapters, llm=lambda p: "")

    def test_explicit_beats_env_beats_candidates(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        candidates_file = plant(home, "OneDrive")
        env_file = tmp_path / "env" / "calendar_sync.json"
        env_file.parent.mkdir()
        env_file.write_bytes(b"{}")
        explicit_file = tmp_path / "chosen" / "my-calendar.json"
        explicit_file.parent.mkdir()
        explicit_file.write_bytes(b"{}")
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", str(env_file))

        bridge = self.make_bridge(tmp_path)
        assert bridge.poll()["path"] == str(env_file)  # env wins over candidates

        set_calendar_path(bridge.conn, str(explicit_file))
        assert bridge.poll()["path"] == str(explicit_file)  # explicit wins over env

        clear_calendar_path(bridge.conn)
        assert bridge.poll()["path"] == str(env_file)

    def test_explicit_set_but_missing_falls_through_to_env(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        env_file = tmp_path / "env" / "calendar_sync.json"
        env_file.parent.mkdir()
        env_file.write_bytes(b"{}")
        monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", str(env_file))

        bridge = self.make_bridge(tmp_path)
        set_calendar_path(bridge.conn, str(tmp_path / "gone.json"))
        assert bridge.poll()["path"] == str(env_file)

    def test_store_round_trip_and_clear(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        bridge = self.make_bridge(tmp_path)
        assert get_calendar_path(bridge.conn) is None

        set_calendar_path(bridge.conn, str(tmp_path / "a.json"))
        assert get_calendar_path(bridge.conn) == str(tmp_path / "a.json")

        set_calendar_path(bridge.conn, str(tmp_path / "b.json"))
        assert get_calendar_path(bridge.conn) == str(tmp_path / "b.json")

        clear_calendar_path(bridge.conn)
        assert get_calendar_path(bridge.conn) is None

    def test_hint_names_the_explicit_path_when_set(self, monkeypatch, tmp_path):
        home = fake_home(monkeypatch, tmp_path)
        plant(home, "OneDrive")  # a real default exists, but is outranked
        explicit = tmp_path / "chosen" / "my-calendar.json"

        assert default_calendar_hint(str(explicit)) == explicit


def test_the_walkthrough_renders_when_the_calendar_is_pinned_off(monkeypatch):
    """The demo and test boot with an empty pin must still show a page.

    The hint used to index the candidate list unconditionally, so this
    boot answered 500 on the walkthrough. The page now renders and names
    the plain default it would use once the pin is lifted.
    """
    monkeypatch.setenv("AGENTDESK_CALENDAR_FILE", "")
    booted = server_harness.Booted()
    try:
        headers = booted.exchange()
        status, _headers, body = booted.request("GET", "/walkthrough/calendar", headers)
        page = body.decode("utf-8")
        assert status == 200, (status, page[:200])
        assert "Connect your calendar" in page
        assert "agent-desk" in page
    finally:
        booted.close()
