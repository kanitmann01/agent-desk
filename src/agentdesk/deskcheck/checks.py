"""The desk's checks, and the fixes they are sure about.

Each check reads one part of the desk's own state and answers with findings.
An automatic fix runs only when the check is confident, the caller asked for
fixing, and the autonomy switch allows it; everything else is a finding the
page offers to the user. A check whose collaborator is absent (a
half-configured desk, a fresh process) returns quietly rather than guessing.
"""

import hashlib

from agentdesk.calendar.watcher import STATE_EMPTY
from agentdesk.deskcheck import fixes as fixes_mod
from agentdesk.deskcheck.core import (
    FIX_ASK,
    FIX_AUTO,
    FIX_LINK,
    FIX_NONE,
    SEVERITY_ATTENTION,
    SEVERITY_INFO,
    CheckResult,
    Finding,
    register,
)
from agentdesk.inbox.core import KIND_SUGGESTION
from agentdesk.ledger import may_act
from agentdesk.server import demo_data


def _plural(count: int, singular: str) -> str:
    """The singular for one, the plain plural for any other count."""
    return singular if count == 1 else singular + "s"


def _joined(words: list[str]) -> str:
    """'a', 'a and b', 'a, b and c' -- the way a sentence lists things."""
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


RETIRED_ASK = "retired-plugins"


def retired_ask_latch_key(ids: list[str]) -> str:
    """The latch key remembering a dismissed retired-plugins ask card."""
    joined = ",".join(sorted(ids))
    return "ask:retired-plugins:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _ensure_retired_ask_card(ctx, retired: list[str]) -> None:
    """Keep exactly one waiting ask card about the retired plugins.

    The card is the ask-first surface: nothing is uninstalled until the
    user accepts it. A waiting card, or a latch from a dismissed one, means
    the question was already asked; a later check run never asks twice.
    """
    if ctx.inbox is None:
        return
    if any(card.meta.get("ask") == RETIRED_ASK
           for card in ctx.inbox.waiting(include_snoozed=True)):
        return
    if ctx.ledger is not None and ctx.ledger.latch_value(
            retired_ask_latch_key(retired)) is not None:
        return
    count = len(retired)
    ctx.inbox.add(
        kind=KIND_SUGGESTION,
        origin=("These plugins left the catalog in this version. "
                "Removing them keeps their data folders."),
        title=f"Remove {count} retired {_plural(count, 'plugin')}",
        body="\n".join(retired),
        action_label="Remove them",
        meta={"ask": RETIRED_ASK, "ids": retired, "count": count},
    )


def _fix_allowed(ctx, finding: Finding, should_fix: bool) -> bool:
    """Whether this finding may be fixed automatically on this run."""
    return (
        should_fix
        and finding.confident
        and finding.fix == FIX_AUTO
        and ctx.settings is not None
        and may_act(ctx.settings, "deskcheck.fix")
    )


def _calendar_connected(calendar) -> bool:
    """Whether the calendar has a document behind it, the same rule the dashboard uses."""
    status = calendar.status() or {}
    return status.get("state") not in (None, STATE_EMPTY)


@register("inbox-unreadable-rows", "Inbox cards this version cannot read")
def inbox_unreadable_rows(ctx, should_fix: bool) -> CheckResult:
    """One row written by a build this one does not know is one card to set aside."""
    if ctx.inbox is None:
        return CheckResult()
    rows = ctx.inbox.unreadable()
    if not rows:
        return CheckResult()
    kinds = sorted({row["kind"] for row in rows})
    count = len(rows)
    if count == 1:
        cause = (f"This version has no card kind called {_joined(kinds)}, so the row "
                 "stays in the inbox database, hidden from the list.")
    else:
        cause = (f"This version has no card kind called {_joined(kinds)}, so those rows "
                 "stay in the inbox database, hidden from the list.")
    finding = Finding(
        id="inbox-unreadable-rows",
        title=f"{count} {_plural(count, 'inbox card')} this version cannot read",
        cause=cause,
        severity=SEVERITY_ATTENTION,
        confident=True,
        fix=FIX_AUTO,
        fix_label="Fix it",
        detail={"count": count, "kinds": kinds},
    )
    if _fix_allowed(ctx, finding, should_fix):
        outcome = fixes_mod.apply_fix(ctx, finding)
        if outcome.fixed:
            return CheckResult(fixed=[outcome.entry_id] if outcome.entry_id else [])
        return CheckResult(findings=[finding], failed={finding.id: outcome.cause or ""})
    return CheckResult(findings=[finding])


@register("sample-not-wired", "Sample data is on but the sample files are not wired")
def sample_not_wired(ctx, should_fix: bool) -> CheckResult:
    """Sample data promises files; the toggles are on but nothing real is attached."""
    if ctx.settings is None:
        return CheckResult()
    if not ctx.settings.get("sample_data"):
        return CheckResult()
    sources = []
    if (ctx.excel is not None and ctx.settings.get("excel_enabled")
            and ctx.excel.registered_path is None):
        sources.append("workbook")
    if (ctx.calendar is not None and ctx.settings.get("calendar_enabled")
            and ctx.calendar.explicit_path() is None):
        sources.append("calendar")
    if not sources:
        return CheckResult()
    text = _joined(sources)
    if len(sources) == 1:
        cause = (f"Sample data turns the {text} on, but no real {text} is attached, "
                 "so the sample rows will not update.")
    else:
        cause = (f"Sample data turns the {text} on, but neither is attached, "
                 "so the sample rows will not update.")
    finding = Finding(
        id="sample-not-wired",
        title="Sample data is on but the sample files are not wired",
        cause=cause,
        severity=SEVERITY_ATTENTION,
        confident=True,
        fix=FIX_AUTO,
        fix_label="Fix it",
        detail={"sources": sources},
    )
    if _fix_allowed(ctx, finding, should_fix):
        outcome = fixes_mod.apply_fix(ctx, finding)
        if outcome.fixed:
            return CheckResult(fixed=[outcome.entry_id] if outcome.entry_id else [])
        return CheckResult(findings=[finding], failed={finding.id: outcome.cause or ""})
    return CheckResult(findings=[finding])


@register("source-on-not-connected", "A source is on but nothing is connected")
def source_on_not_connected(ctx, should_fix: bool) -> CheckResult:
    """A real source switch is on, sample off, and nothing is connected behind it."""
    if ctx.settings is None:
        return CheckResult()
    if ctx.settings.get("sample_data"):
        return CheckResult()
    unconnected = []
    if (ctx.excel is not None and ctx.settings.get("excel_enabled")
            and ctx.excel.registered_path is None):
        unconnected.append(("workbook", "/settings#sources"))
    if (ctx.calendar is not None and ctx.settings.get("calendar_enabled")
            and not _calendar_connected(ctx.calendar)):
        unconnected.append(("calendar", "/walkthrough/calendar"))
    if not unconnected:
        return CheckResult()
    ids = [source_id for source_id, _href in unconnected]
    if ids == ["workbook"]:
        title = "Workbook watching is on but no workbook is connected"
    elif ids == ["calendar"]:
        title = "Calendar reading is on but no calendar is connected"
    else:
        title = "Workbook and calendar are on but neither is connected"
    return CheckResult(findings=[Finding(
        id="source-on-not-connected",
        title=title,
        cause="The switch is on, but nothing is attached yet, so the desk only shows "
              "the not-connected state.",
        severity=SEVERITY_ATTENTION,
        confident=False,
        fix=FIX_LINK,
        fix_label="Open",
        href=unconnected[0][1],
        detail={"sources": ids},
    )])


def _bundled_catalog_ids(ctx):
    """Plugin ids from the shipped catalog, or None when it cannot be judged.

    A caller that already resolved the catalog (the tests) passes that set,
    including an empty one. None means nobody loaded it yet, so this check
    loads the shipped file itself. An empty file is None and the check stays
    quiet, instead of calling every installed plugin retired. A load that
    raises leaves this function, and the runner records one crashed check.
    """
    if ctx.catalog_ids is not None:
        return ctx.catalog_ids
    from agentdesk.marketplace.catalog import bundled_catalog_path, load_catalog_file

    catalog = load_catalog_file(bundled_catalog_path(), "bundled")
    if not catalog:
        return None
    return frozenset(entry["id"] for entry in catalog)


@register("retired-plugins-installed", "Installed plugins the catalog no longer carries")
def retired_plugins_installed(ctx, should_fix: bool) -> CheckResult:
    """Installed plugins the bundled catalog no longer carries."""
    if ctx.plugins is None:
        return CheckResult()
    catalog_ids = _bundled_catalog_ids(ctx)
    if catalog_ids is None:
        return CheckResult()
    retired = sorted(
        record["id"] for record in ctx.plugins.list_records()
        if record.get("state") != "uninstalled"
        and record.get("id") not in catalog_ids
    )
    if not retired:
        return CheckResult()
    count = len(retired)
    _ensure_retired_ask_card(ctx, retired)
    return CheckResult(findings=[Finding(
        id="retired-plugins-installed",
        title=f"{count} installed {_plural(count, 'plugin')} the catalog no longer carries",
        cause="Installed plugins are expected to come from the bundled catalog; "
              f"{'this id is' if count == 1 else 'these ids are'} not in it any more.",
        severity=SEVERITY_ATTENTION,
        confident=False,
        fix=FIX_ASK,
        fix_label="Review card",
        detail={"ids": retired},
    )])


@register("sample-plugin-not-installed", "The sample plugin is not installed")
def sample_plugin_not_installed(ctx, should_fix: bool) -> CheckResult:
    """Sample data draws a plugin cell, but the sample plugin was never installed."""
    if ctx.settings is None or ctx.plugins is None:
        return CheckResult()
    if not ctx.settings.get("sample_data"):
        return CheckResult()
    installed = {
        record.get("id") for record in ctx.plugins.list_records()
        if record.get("state") != "uninstalled"
    }
    if demo_data.SAMPLE_PLUGIN_ID in installed:
        return CheckResult()
    return CheckResult(findings=[Finding(
        id="sample-plugin-not-installed",
        title="The sample plugin is not installed",
        cause="Sample data draws a plugin cell, but the sample plugin is not installed, "
              "so that cell stays empty.",
        severity=SEVERITY_INFO,
        confident=False,
        fix=FIX_LINK,
        fix_label="Open",
        href=f"/marketplace/plugin/{demo_data.SAMPLE_PLUGIN_ID}",
    )])


@register("fix-failing", "A fix the desk tried keeps failing")
def fix_failing(ctx, should_fix: bool) -> CheckResult:
    """Fixes that failed three times in a row, shown with their last cause."""
    return CheckResult(findings=fixes_mod.fix_failing_findings(ctx))
