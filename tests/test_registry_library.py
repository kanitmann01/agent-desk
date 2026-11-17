"""The registry library (#65): four new Class D plugins ship together.

excel-report, calendar-today, outlook-digest and research-brief publish
beside sales-delta-widget as tag-pinned releases. These tests hold the
whole publishing contract: the shared validator accepts each plugin,
registry CI passes over the mutated index, each release's pin equals the
recomputed tree digest, every card binds only names its own source type
computes, and a pinned install through the real registry path renders
live values from the real pipelines (and honest amber with a cause when
the pipeline is empty).
"""
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import excel_fixtures  # noqa: E402
from registry_fixtures import git as git_run  # noqa: E402

from agentdesk.plugins.execute import BINDINGS, PluginWidgetRunner  # noqa: E402
from agentdesk.plugins.render import ELEMENT_KINDS  # noqa: E402
from agentdesk.plugins.runtime import PluginRuntime  # noqa: E402
from agentdesk.registry.index import load_index  # noqa: E402
from agentdesk.registry.install import install_from_registry, tree_digest  # noqa: E402
from agentdesk.validator.core import validate_plugin  # noqa: E402

REGISTRY = ROOT / "registry"
PLUGINS = REGISTRY / "plugins"

# The published library: id -> latest version. sales-delta-widget is the
# existing first publish; the other four are this ticket's additions.
LIBRARY = {
    "sales-delta-widget": "0.2.0",
    "excel-report": "0.1.0",
    "calendar-today": "0.2.0",
    "outlook-digest": "0.2.0",
    "research-brief": "0.2.0",
}
NEW_IDS = ["excel-report", "calendar-today", "outlook-digest",
           "research-brief"]

# The binding vocabulary per data source type, pinned from the runner's
# documented sets: a card may only bind names its own source computes.
SOURCE_BINDINGS = {
    "excel-watch": {"delta24h", "addedCount", "removedCount", "unchangedCount",
                    "rowsSeen", "file", "windowNote"},
    "calendar-read": {"nextEventTitle", "nextEventTime", "eventsToday",
                      "windowNote"},
    "mail-digest": {"messages", "threads", "topSenders", "windowNote"},
    "research-brief": {"summary", "sourcesCount", "answeredAt", "windowNote"},
}

CALENDAR_WINDOW_NOTE = ("The next commitment and today's count, from the "
                        "calendar file your flow syncs.")
MAIL_WINDOW_NOTE = ("Counts cover the last 24 hours of message headers; "
                    "bodies are never read.")
RESEARCH_WINDOW_NOTE = ("The latest stored research answer; showing it "
                        "made no endpoint call.")
EXCEL_BASELINE_NOTE = ("The first snapshot is the baseline; the next poll "
                       "diffs against it.")

DAY = 24 * 60 * 60.0


# ---- the publishing contract ------------------------------------------


@pytest.mark.parametrize("plugin_id", NEW_IDS)
def test_shared_validator_accepts_each_new_plugin(plugin_id):
    verdict = validate_plugin(PLUGINS / plugin_id)
    assert verdict.ok, verdict.failures


@pytest.mark.parametrize("plugin_id", LIBRARY)
def test_every_plugin_stays_inside_the_declarative_vocabulary(plugin_id):
    """No network, no shell, no LLM, no unscoped glob, no HTML: the
    permission blocks are the deny shape the lint enforces."""
    manifest = json.loads((PLUGINS / plugin_id / "manifest.json").read_text(
        encoding="utf-8"))
    assert manifest["class"] == "declarative"
    permissions = manifest["permissions"]
    assert permissions["network"]["allow"] == []
    assert permissions["shell"] == "none"
    assert permissions["llm"]["allow"] is False
    for glob in permissions["filesystem"].get("read", []):
        assert glob.startswith("${workspace}/") or glob == "${pluginData}"
    render = manifest["contributes"]["widgets"][0]["render"]
    assert render["type"] == "ui-schema"
    assert render["file"].endswith(".json")


def test_registry_ci_passes_over_the_mutated_index():
    """The same review CI runs (shared validator, dependency scan, hash
    consistency, append-only history) passes with all four plugins added
    on top of the pre-#65 single-plugin index."""
    from agentdesk.registry.ci import review_registry_changes

    base = json.loads((REGISTRY / "index.json").read_text(encoding="utf-8"))
    base["plugins"] = [entry for entry in base["plugins"]
                       if entry["id"] == "sales-delta-widget"]
    result = review_registry_changes(REGISTRY, [PLUGINS / pid for pid in LIBRARY],
                                     base_index_text=json.dumps(base))
    assert result == {"ok": True, "reasons": []}, result["reasons"]


def test_index_pins_match_the_published_trees():
    index = load_index((REGISTRY / "index.json").read_text(encoding="utf-8"))
    assert set(LIBRARY) <= {entry.id for entry in index.plugins}
    for plugin_id, version in LIBRARY.items():
        entry = index.plugin(plugin_id)
        assert entry is not None, plugin_id
        release = entry.release_for(version)
        assert release is not None, plugin_id
        if release.source == "local":
            assert release.tag == ""
        else:
            assert release.tag == f"{entry.id}-{release.version}"
        assert release.yanked is False
        assert entry.class_ == "declarative"
        assert entry.risk == "low"
        assert release.sha256 == tree_digest(PLUGINS / entry.id), entry.id


def test_listing_payload_carries_the_whole_library():
    """The /plugins page's listing payload names all five entries with
    their pinned releases, the payload the registry bridge serves."""
    from agentdesk.registry.source import registry_listing

    listing = registry_listing(REGISTRY)
    assert listing["ok"] is True, listing
    entries = listing["plugins"]
    by_id = {entry["id"]: entry for entry in entries}
    assert set(LIBRARY) <= set(by_id)
    assert len(entries) == len(load_index(
        (REGISTRY / "index.json").read_text(encoding="utf-8")).plugins)
    for plugin_id, version in LIBRARY.items():
        entry = by_id[plugin_id]
        assert entry["class"] == "declarative"
        assert entry["latest"] == version
        release = next(item for item in entry["releases"]
                       if item["version"] == version)
        if release["source"] == "tag":
            assert release["tag"] == f"{plugin_id}-{version}"
        else:
            assert release["tag"] == ""
        assert release["yanked"] is False


def test_every_card_binds_only_names_its_source_computes():
    """Unknown-binding safety, pinned at the source: the per-type sets
    together are exactly the runner's vocabulary, and every binding in
    every committed ui-schema belongs to its own source's set."""
    for plugin_id in LIBRARY:
        manifest = json.loads((PLUGINS / plugin_id / "manifest.json").read_text(
            encoding="utf-8"))
        widget = manifest["contributes"]["widgets"][0]
        source_type = widget["dataSource"]["type"]
        schema = json.loads(
            (PLUGINS / plugin_id / widget["render"]["file"]).read_text(
                encoding="utf-8"))
        kinds = {element["type"] for element in schema["elements"]}
        assert kinds <= set(ELEMENT_KINDS), plugin_id
        bound = {element["binding"] for element in schema["elements"]
                 if "binding" in element}
        assert bound, plugin_id  # a card that binds nothing is no card
        assert bound <= set(BINDINGS), (plugin_id, bound)


# ---- the install-and-render pipeline ----------------------------------


@pytest.fixture(scope="session")
def library_registry(tmp_path_factory):
    """The committed registry as a real git checkout with every release
    tagged, byte-exact (no line-ending conversion anywhere), so the
    pinned install path exercises exactly what a client downloads."""
    repo = tmp_path_factory.mktemp("library") / "registry"
    shutil.copytree(REGISTRY / "plugins", repo / "plugins")
    shutil.copy2(REGISTRY / "index.json", repo / "index.json")
    index = load_index((repo / "index.json").read_text(encoding="utf-8"))
    git_run(repo, "init", "-q", "-b", "main")
    git_run(repo, "config", "core.autocrlf", "false")
    (repo / ".gitattributes").write_text("* -text\n", encoding="utf-8")
    git_run(repo, "add", "-A")
    git_run(repo, "commit", "-qm", "library")
    for entry in index.plugins:
        for release in entry.releases:
            git_run(repo, "tag", "-a", release.tag, "-m",
                    f"{entry.id} {release.version}")
    return repo


def _install(tmp_path, library_registry, plugin_id, workspace, runner):
    """One pinned install through the real registry path, then the
    runtime's own install of the staged, verified directory."""
    from agentdesk.registry.install import install_from_registry

    staged = tmp_path / "staged"
    out = install_from_registry(library_registry, plugin_id,
                                version=LIBRARY[plugin_id],
                                destination=staged)
    assert out["ok"] is True
    runtime = PluginRuntime(plugins_dir=tmp_path / "plugins",
                            data_dir=tmp_path / "plugin-data",
                            workspace_dir=workspace, runner=runner)
    result = runtime.install(Path(out["path"]), source="registry")
    assert result["ok"] is True
    return runtime


def _one_card(runtime):
    cards = runtime.widget_cards()
    assert len(cards) == 1
    return cards[0]


def _element(payload, kind, label=None):
    for element in payload["elements"]:
        if element.get("kind") != kind:
            continue
        if label is not None and element.get("label") != label:
            continue
        return element
    raise AssertionError(f"no {kind} element with label {label!r}")


# The seeded pipelines, the same objects the dashboard's own cards read.


def _calendar_bridge(now: datetime, events):
    from agentdesk.calendar.watcher import Adapters as CalendarAdapters
    from agentdesk.calendar.watcher import CalendarBridge

    def read_calendar():
        if events is None:
            return None
        doc = json.dumps({"generatedAt": now.isoformat(), "events": events})
        return ("onedrive/agent-desk/calendar_sync.json", doc.encode("utf-8"))

    adapters = CalendarAdapters(read_calendar=read_calendar,
                                clock=lambda: now.timestamp())
    bridge = CalendarBridge(
        sqlite3.connect(":memory:", check_same_thread=False), adapters,
        llm=lambda _p: '{"subtasks": [], "followups": []}')
    bridge.poll()
    return bridge


def _today_events(now: datetime):
    return [
        {"id": "a", "subject": "Q4 pipeline review",
         "start": now.replace(hour=14).isoformat(),
         "end": now.replace(hour=15).isoformat()},
        {"id": "b", "subject": "Later sync",
         "start": now.replace(hour=16).isoformat(),
         "end": now.replace(hour=17).isoformat()},
        {"id": "c", "subject": "Tomorrow",
         "start": (now + timedelta(days=1)).replace(hour=10).isoformat(),
         "end": (now + timedelta(days=1)).replace(hour=11).isoformat()},
    ]


def _eml(message_id: str, subject: str, sender: str, date_ts: float,
         in_reply_to: str = "") -> bytes:
    from email.utils import formatdate

    lines = [
        f"From: {sender}",
        "To: employee@example.com",
        f"Subject: {subject}",
        f"Date: {formatdate(date_ts, usegmt=True)}",
        f"Message-ID: {message_id}",
    ]
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    lines += ["MIME-Version: 1.0",
              "Content-Type: text/plain; charset=utf-8",
              "",
              "a body that must never reach a card"]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _mail_watch(tmp_path, now_ts: float, files: dict, folder: str):
    from agentdesk.inbox.store import InboxStore
    from agentdesk.mail.core import read_eml_folder_reported
    from agentdesk.mail.store import MailStore
    from agentdesk.mail.watcher import Adapters as MailAdapters
    from agentdesk.mail.watcher import MailWatch

    folder_path = tmp_path / "mail"
    folder_path.mkdir(exist_ok=True)
    for name, raw in files.items():
        (folder_path / name).write_bytes(raw)
    return MailWatch(
        inbox=InboxStore(sqlite3.connect(":memory:", check_same_thread=False),
                         lambda: now_ts),
        store=MailStore(sqlite3.connect(":memory:", check_same_thread=False),
                        lambda: now_ts),
        adapters=MailAdapters(read_folder=read_eml_folder_reported,
                              clock=lambda: now_ts),
        folder_provider=lambda: folder,
    )


def _research_store(now_ts: float, answer=None):
    from agentdesk.assistant.research_store import ResearchStore

    store = ResearchStore(
        sqlite3.connect(":memory:", check_same_thread=False),
        clock=lambda: now_ts)
    if answer is not None:
        store.save(answer[0], answer[1])
    return store


def _excel_runner(workspace: Path, tmp_path: Path, clock: list[float]):
    """The real excel pipeline (shadow copy, stdlib parser) over a real
    .xlsx, with the shadow dir kept inside the test's temp tree. The
    clock is a one-cell list the test moves between windows."""
    from agentdesk.excel import shadow as shadow_mod
    from agentdesk.excel import xlsx as xlsx_mod
    from agentdesk.excel.watcher import Adapters

    return PluginWidgetRunner(
        workspace, adapters=Adapters(
            copy_shadow=lambda path: shadow_mod.copy_to_shadow(
                path, workdir=tmp_path / "shadow"),
            parse_workbook=xlsx_mod.parse_workbook_file,
            clock=lambda: clock[0]))


# ---- excel-report ------------------------------------------------------


def test_excel_report_installs_and_waits_for_a_confirmed_file(tmp_path):
    workspace = tmp_path / "workspace" / "reports"
    workspace.mkdir(parents=True)
    (workspace / "report.xlsx").write_bytes(
        excel_fixtures.make_xlsx(excel_fixtures.BASE_ROWS))
    clock = [1_000_000.0]
    runner = _excel_runner(workspace.parent, tmp_path, clock)
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "plugin-data",
        workspace_dir=workspace.parent, runner=runner)
    runtime.install(PLUGINS / "excel-report", source="dir")
    card = _one_card(runtime)
    assert card["id"] == "excel-report"
    assert card["freshness"] == "setup"
    assert card["payload"]["setup"]["step"] == "source"
    # A workbook sitting in the old reports folder is not read on install.
    assert card["payload"]["elements"] == []


def test_excel_report_with_no_workbook_asks_for_one(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = _excel_runner(workspace, tmp_path, [1_000_000.0])
    runtime = PluginRuntime(
        plugins_dir=tmp_path / "plugins", data_dir=tmp_path / "plugin-data",
        workspace_dir=workspace, runner=runner)
    runtime.install(PLUGINS / "excel-report", source="dir")
    card = _one_card(runtime)
    assert card["freshness"] == "setup"
    assert card["cause"] == ""
    assert card["payload"]["setup"]["step"] == "source"


# ---- calendar-today ----------------------------------------------------


def test_calendar_today_installs_and_binds_the_day(tmp_path, library_registry):
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = PluginWidgetRunner(workspace,
                                calendar=_calendar_bridge(now,
                                                          _today_events(now)))
    runtime = _install(tmp_path, library_registry, "calendar-today",
                       workspace, runner)
    card = _one_card(runtime)
    assert card["id"] == "calendar-today"
    assert card["freshness"] == "fresh"
    payload = card["payload"]
    assert payload["status"] == "fresh"
    assert _element(payload, "metric", "Events today")["value"] == "2"
    assert _element(payload, "text", "Next")["text"] == "Q4 pipeline review"
    rows = _element(payload, "list")["rows"]
    assert len(rows) == 2
    assert rows[0]["primary"] == "Q4 pipeline review"
    assert rows[1]["primary"] == "Later sync"
    assert rows[0]["secondary"] == now.replace(hour=14).strftime("%H:%M")


def test_calendar_today_with_no_calendar_is_amber_with_cause(
        tmp_path, library_registry):
    now = datetime(2026, 11, 13, 9, 0, 0).astimezone()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = PluginWidgetRunner(workspace,
                                calendar=_calendar_bridge(now, None))
    runtime = _install(tmp_path, library_registry, "calendar-today",
                       workspace, runner)
    card = _one_card(runtime)
    assert card["freshness"] == "attention"
    assert "calendar" in card["cause"].lower()
    payload = card["payload"]
    assert payload["status"] == "attention"
    assert payload["elements"] == []


# ---- outlook-digest ----------------------------------------------------


def test_outlook_digest_installs_and_binds_header_counts(
        tmp_path, library_registry):
    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    files = {
        "m1.eml": _eml("<1@x>", "Q4 pricing", "a@example.com", now - 2 * 3600),
        "m2.eml": _eml("<2@x>", "Re: Q4 pricing", "b@example.com",
                       now - 3600, in_reply_to="<1@x>"),
        "m3.eml": _eml("<3@x>", "Re: Q4 pricing", "a@example.com",
                       now - 1800, in_reply_to="<2@x>"),
        "m4.eml": _eml("<4@x>", "Old thread", "c@example.com", now - 3 * DAY),
    }
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = PluginWidgetRunner(
        workspace, mail=_mail_watch(tmp_path, now, files,
                                    folder=str(tmp_path / "mail")))
    runtime = _install(tmp_path, library_registry, "outlook-digest",
                       workspace, runner)
    card = _one_card(runtime)
    assert card["id"] == "outlook-digest"
    assert card["freshness"] == "fresh"
    payload = card["payload"]
    assert payload["status"] == "fresh"
    assert _element(payload, "metric", "Messages 24h")["value"] == "3"
    senders = _element(payload, "list")["rows"]
    assert [row["primary"] for row in senders] == [
        "a@example.com", "b@example.com"]
    assert _element(payload, "text", "Scope")["text"] == MAIL_WINDOW_NOTE
    # Metadata only: no message body ever rides along.
    assert "a body that must never reach a card" not in json.dumps(payload)


def test_outlook_digest_without_a_folder_is_amber_with_cause(
        tmp_path, library_registry):
    now = datetime(2026, 11, 13, 12, 0, 0).astimezone().timestamp()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = PluginWidgetRunner(workspace,
                                mail=_mail_watch(tmp_path, now, {},
                                                 folder=""))
    runtime = _install(tmp_path, library_registry, "outlook-digest",
                       workspace, runner)
    card = _one_card(runtime)
    assert card["freshness"] == "attention"
    assert "Settings" in card["cause"]
    payload = card["payload"]
    assert payload["status"] == "attention"
    assert payload["elements"] == []


# ---- research-brief ----------------------------------------------------


def test_research_brief_installs_and_binds_the_latest_answer(
        tmp_path, library_registry):
    now = datetime(2026, 11, 13, 9, 41, 0).astimezone()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = PluginWidgetRunner(
        workspace, research=_research_store(
            now.timestamp(),
            ("Five of nine EU partners reflected the new prices.",
             ["eu-price-memo.pdf", "channel-weekly.xlsx"])))
    runtime = _install(tmp_path, library_registry, "research-brief",
                       workspace, runner)
    card = _one_card(runtime)
    assert card["id"] == "research-brief"
    assert card["freshness"] == "fresh"
    payload = card["payload"]
    assert payload["status"] == "fresh"
    assert _element(payload, "text", "Latest answer")["text"] == (
        "Five of nine EU partners reflected the new prices.")
    assert _element(payload, "metric", "Sources")["value"] == "2"
    assert _element(payload, "text", "Answered")["text"] == "2026-11-13 09:41"


def test_research_brief_with_nothing_asked_is_amber_with_cause(
        tmp_path, library_registry):
    now = datetime(2026, 11, 13, 9, 41, 0).astimezone()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = PluginWidgetRunner(workspace,
                                research=_research_store(now.timestamp()))
    runtime = _install(tmp_path, library_registry, "research-brief",
                       workspace, runner)
    card = _one_card(runtime)
    assert card["freshness"] == "attention"
    assert "Research" in card["cause"]
    payload = card["payload"]
    assert payload["status"] == "attention"
    assert payload["elements"] == []
