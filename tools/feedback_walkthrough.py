"""Walk the desk's model-backed actions and photograph their feedback.

The walk boots the same isolated desk as ``tools/layout_audit.py``: a
temporary data folder, a file-backed fake keychain, a loopback mock model,
and no real ``~/.agent-desk``. It seeds the ``full`` condition, saves a
connection to the mock, and then exercises up to seven actions. Each action
gets three photographs (early wait, after ten seconds, and result) plus the
facts the feedback rules depend on.

The mock answer is delayed by twelve seconds, which is long enough for the
ten-second honesty line. The mock holds the response body open with
whitespace while it waits, so the desk's ten-second idle socket cap does not
preempt the line; the JSON content still lands after the full delay.

Usage, from anywhere:

    uv run --no-project --with playwright --with keyring --with cryptography \\
        python "<worktree>/tools/feedback_walkthrough.py"

Exit codes: 0 when every present action met its feedback rule (optional
actions may be absent), 1 when an action was present but did not meet it,
and 2 when the browser or desk could not start.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import layout_audit as audit

ROOT = audit.ROOT
DEFAULT_OUT = ROOT / "build" / "feedback-walkthrough"
FIXED_TIME = audit.FIXED_TIME
DEFAULT_DELAY_MS = 12000
EARLY_MS = 1500
LATE_MS = 11000
RESULT_TIMEOUT_MS = 180000
VIEWPORT = {"width": 1280, "height": 900}
SLOW_PHRASE = "taking longer than usual"

QUESTION = (
    "What changed in the regional pipeline this week, and which three deals "
    "need an owner before Friday?"
)
ASSISTANT_QUESTION = (
    "What should I do about the pipeline this week, and what can wait?"
)
PRESENTATION_TOPIC = "Q4 pipeline review for the regional leadership team"
WIZARD_DESCRIPTION = (
    "Show me the open pipeline deals by stage with the amount still at risk."
)

BLOCK_SUBMIT_JS = """() => {
  window.__feedbackWalkBlock = (event) => { event.preventDefault(); };
  window.addEventListener('submit', window.__feedbackWalkBlock, true);
}"""

SNAPSHOT_JS = r"""
(arg) => {
  function visible(el) {
    if (!el || !el.isConnected) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (!(parseFloat(style.opacity || '1') > 0.01)) return false;
    const box = el.getBoundingClientRect();
    return box.width >= 1 && box.height >= 1;
  }
  function text(el) {
    return (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  }
  function path(el) {
    const parts = [el.tagName.toLowerCase()];
    const classes = Array.from(el.classList || []).slice(0, 3);
    if (classes.length) parts[0] += '.' + classes.join('.');
    return parts.join('.');
  }
  function find(selector) {
    if (!selector) return null;
    try { return document.querySelector(selector); } catch (error) { return null; }
  }
  let control = find(arg.control);
  if (!control) control = find(arg.fallback_control);
  let region = find(arg.region);
  if (!region) region = find(arg.fallback_region);
  const pending = region
    ? region.querySelector('[data-wait-ph],.pending-shape,.phase-line')
    : null;
  const phaseNode = pending
    ? (pending.querySelector('.wait-line,.phase-line') || pending)
    : null;
  const rows = pending
    ? pending.querySelectorAll(
        '.wait-row,.wait-wire > *,.wire-lines span,.wire-chart span').length
    : 0;
  const answer = region && arg.answer
    ? Array.from(region.querySelectorAll(arg.answer))
        .map((node) => text(node)).filter(Boolean).slice(0, 4)
    : [];
  const alerts = region
    ? Array.from(region.querySelectorAll('[role="alert"],.alert'))
        .map((node) => text(node)).filter(Boolean).slice(0, 4)
    : [];
  const controlBox = control ? control.getBoundingClientRect() : null;
  const waitForm = control && control.form ? control.form : null;
  return {
    url: location.pathname + location.search,
    wait_shape: waitForm ? (waitForm.getAttribute('data-wait-shape') || '') : '',
    wait_label: waitForm ? (waitForm.getAttribute('data-wait-label') || '') : '',
    control: control ? {
      tag: control.tagName.toLowerCase(),
      path: path(control),
      text: (control.innerText || control.value || control.getAttribute('aria-label') || '')
        .replace(/\s+/g, ' ').trim().slice(0, 160),
      aria_busy: control.getAttribute('aria-busy') || '',
      aria_disabled: control.getAttribute('aria-disabled') || '',
      disabled: !!control.disabled,
      classes: String(control.className || ''),
      rect: controlBox ? {x: controlBox.x, y: controlBox.y,
                          width: controlBox.width, height: controlBox.height} : null,
    } : null,
    region: region ? {
      path: path(region),
      aria_busy: region.getAttribute('aria-busy') || '',
      text: text(region).slice(0, 5000),
    } : null,
    pending: !!pending,
    phase: phaseNode ? text(phaseNode).slice(0, 600) : '',
    placeholder_text: pending ? text(pending).slice(0, 1200) : '',
    rows: rows,
    slow: !!(region && /taking longer than usual/i.test(text(region))),
    answer: answer,
    alerts: alerts,
    reply_count: region ? region.querySelectorAll('.answer.reply').length : 0,
    has_download: !!(region && /Download \.pptx/i.test(text(region))),
    has_template: !!(region && /\bTemplate\b/.test(text(region))),
    has_degraded: !!(region && /\[degraded\]|could not|did not answer/i.test(text(region))),
    body_text: document.body ? text(document.body).slice(0, 8000) : '',
  };
}
"""


@dataclass(frozen=True)
class Action:
    """One model-backed control the walk exercises."""

    id: str
    title: str
    route: str
    mode: str
    required: bool
    trigger: str
    trigger_text: str = ""
    scope: str = ""
    scope_text: str = ""
    fill_selector: str = ""
    fill_text: str = ""
    region: str = ""
    answer: str = ""
    absent_reason: str = "the control is not on this desk"
    result_control: str = ""


ACTIONS = (
    Action(
        id="dashboard-research",
        title="Dashboard command bar: Research",
        route="/",
        mode="research",
        required=True,
        trigger="button.cmd-send",
        trigger_text="Research",
        fill_selector='textarea[aria-label="Research question"]',
        fill_text=QUESTION,
        region="section.brief-answer",
        answer=".brief-answer-copy",
        absent_reason="the research command bar is not available",
    ),
    Action(
        id="dashboard-explain",
        title="Dashboard hero chart: Explain this range",
        route="/",
        mode="press",
        required=False,
        trigger="button",
        trigger_text="Explain this range",
        scope=".tracker-card",
        region=".tracker-card",
        answer=".w-body-inner .w-note",
        absent_reason="no live tracker reading offers a press",
    ),
    Action(
        id="dashboard-reply",
        title="Dashboard reading: Draft a reply",
        route="/",
        mode="press",
        required=False,
        trigger="button",
        trigger_text=r"Draft (a|the) reply",
        scope="article.cell, .tracker-card, article.widget",
        answer=".w-body-inner .w-note",
        absent_reason="no dashboard reading offers a reply draft",
    ),
    Action(
        id="assistant-ask",
        title="Assistant: Ask",
        route="/assistant",
        mode="server",
        required=True,
        trigger='form[action="/assistant/ask"] button[type="submit"]',
        trigger_text="Ask",
        fill_selector='textarea[name="question"]',
        fill_text=ASSISTANT_QUESTION,
        region="#assistant-thread",
        answer=".answer.reply",
        absent_reason="the assistant ask form is not available",
    ),
    Action(
        id="agents-presentation",
        title="Agents: Run Presentation",
        route="/agents",
        mode="server",
        required=True,
        trigger='#agent-presentation button[type="submit"]',
        trigger_text="Run Presentation",
        fill_selector="#brief-presentation",
        fill_text=PRESENTATION_TOPIC,
        region="#agents-history",
        answer="article",
        absent_reason="the presentation form is not available",
    ),
    Action(
        id="wizard-describe",
        title="Wizard: describe a plugin",
        route="/wizard",
        mode="server",
        required=True,
        trigger='form[action="/wizard/new/answer"] button[type="submit"]',
        trigger_text="Ask",
        fill_selector="#wizard-description",
        fill_text=WIZARD_DESCRIPTION,
        region="main#main",
        answer=".aq",
        absent_reason="the wizard describe form is not available",
        result_control='form.answer button[type="submit"]',
    ),
    Action(
        id="inbox-draft",
        title="Inbox waiting card: Draft a reply",
        route="/inbox",
        mode="press",
        required=False,
        trigger='article.widget button, article.widget a',
        trigger_text=r"Draft (a|the) reply",
        scope="article.widget",
        answer=".w-body-inner .w-note",
        absent_reason="no waiting card offers a model-backed reply draft",
    ),
)


def _now_stamp() -> str:
    """A filesystem-friendly timestamp for one run folder."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    """The same instant as a UTC ISO string for the manifest."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _visible(locator) -> bool:
    """True when the first matching element is visible; failures are False."""
    try:
        return locator.count() > 0 and locator.first.is_visible()
    except Exception:  # noqa: BLE001 - a detached node is simply not visible
        return False


def _locator_for(page, action: Action):
    """The first visible trigger for an action, or None.

    ``scope`` narrows the search to a card; ``trigger_text`` is matched
    case-insensitively inside the trigger. A selector that matches several
    elements takes the first visible one.
    """
    try:
        root = page.locator(action.scope) if action.scope else page
        if action.scope_text:
            root = root.filter(has_text=re.compile(action.scope_text, re.I))
        matches = root.locator(action.trigger)
        if action.trigger_text:
            matches = matches.filter(has_text=re.compile(action.trigger_text, re.I))
        for index in range(min(matches.count(), 20)):
            candidate = matches.nth(index)
            if _visible(candidate):
                return candidate
    except Exception:  # noqa: BLE001 - a malformed page has no trigger
        return None
    return None


def _element_facts(locator) -> dict:
    """A control's label, path and box, or an empty object."""
    try:
        return locator.evaluate(
            """(el) => {
              const box = el.getBoundingClientRect();
              const classes = Array.from(el.classList || []).slice(0, 3);
              const tag = el.tagName.toLowerCase();
              return {
                tag: tag,
                path: classes.length ? tag + '.' + classes.join('.') : tag,
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '')
                  .replace(/\\s+/g, ' ').trim().slice(0, 160),
                rect: {x: box.x, y: box.y, width: box.width, height: box.height},
                formShape: el.form ? (el.form.getAttribute('data-wait-shape') || '') : '',
                formWaitLabel: el.form
                  ? (el.form.getAttribute('data-wait-label') || '') : '',
              };
            }""")
    except Exception:  # noqa: BLE001 - evidence may be gone after navigation
        return {}


def _mark(page, action: Action, trigger) -> None:
    """Mark the trigger and its nearest card so later snapshots find them."""
    try:
        trigger.evaluate(
            "(el, name) => el.setAttribute('data-feedback-walkthrough', name)",
            action.id)
    except Exception:  # noqa: BLE001 - the next snapshot falls back to the selector
        pass
    if action.mode == "server":
        return
    try:
        trigger.evaluate(
            """(el, name) => {
              const card = el.closest('.tracker-card, article.cell, article.widget, article');
              if (card) card.setAttribute('data-feedback-region', name);
            }""", action.id)
    except Exception:  # noqa: BLE001 - the action may live outside a card
        pass


def _snapshot(page, action: Action) -> dict:
    """The control, region, pending state and result text on the page now."""
    argument = {
        "control": f'[data-feedback-walkthrough="{action.id}"]',
        "fallback_control": action.result_control or action.trigger,
        "region": ("" if action.mode == "server"
                   else f'[data-feedback-region="{action.id}"]'),
        "fallback_region": action.region,
        "answer": action.answer,
    }
    return page.evaluate(SNAPSHOT_JS, argument)


def _is_busy(snapshot: dict) -> bool:
    """True when the control advertises the wait in words or ARIA."""
    control = snapshot.get("control") or {}
    label = str(control.get("text") or "").lower()
    classes = str(control.get("classes") or "").lower()
    busy_words = ("asking", "explaining", "drafting", "building", "running", "saving")
    return (
        str(control.get("aria_busy") or "") == "true"
        or "is-busy" in classes
        or any(word in label for word in busy_words)
    )


def _is_idle(snapshot: dict) -> bool:
    """True when the control is visible and no longer carrying a wait."""
    control = snapshot.get("control") or {}
    return bool(control) and not _is_busy(snapshot) \
        and not control.get("disabled") \
        and str(control.get("aria_disabled") or "") != "true"


def _facts(snapshot: dict) -> dict:
    """The JSON-safe facts one photograph is paired with."""
    return {
        "url": snapshot.get("url", ""),
        "waitShape": str(snapshot.get("wait_shape") or ""),
        "waitLabel": str(snapshot.get("wait_label") or ""),
        "control": snapshot.get("control"),
        "region": snapshot.get("region"),
        "busy": _is_busy(snapshot),
        "idle": _is_idle(snapshot),
        "pending": bool(snapshot.get("pending")),
        "same_shape": bool(snapshot.get("pending")) and int(snapshot.get("rows") or 0) > 0,
        "rows": int(snapshot.get("rows") or 0),
        "phase": str(snapshot.get("phase") or ""),
        "placeholder_text": str(snapshot.get("placeholder_text") or ""),
        "slow": bool(snapshot.get("slow")),
        "answer": [] if snapshot.get("pending") else (snapshot.get("answer") or []),
        "alerts": snapshot.get("alerts") or [],
        "reply_count": int(snapshot.get("reply_count") or 0),
        "has_download": bool(snapshot.get("has_download")),
        "has_template": bool(snapshot.get("has_template")),
        "has_degraded": bool(snapshot.get("has_degraded")),
    }


def _result_ready(action: Action, snapshot: dict) -> bool:
    """True when the wait has ended and a result or refusal is on screen."""
    if snapshot.get("pending"):
        return False
    if snapshot.get("alerts"):
        return True
    if action.mode in ("research", "press"):
        return bool(snapshot.get("answer"))
    if action.id == "assistant-ask":
        return int(snapshot.get("reply_count") or 0) > 0
    if action.id == "agents-presentation":
        return bool(snapshot.get("has_download")
                    or snapshot.get("has_template")
                    or snapshot.get("has_degraded"))
    return bool(snapshot.get("answer") or snapshot.get("has_degraded"))


def _result_ok(action: Action, snapshot: dict) -> bool:
    """True when the action produced a real result rather than a refusal."""
    if snapshot.get("pending") or snapshot.get("alerts"):
        return False
    if action.mode in ("research", "press"):
        return bool(snapshot.get("answer"))
    if action.id == "assistant-ask":
        return int(snapshot.get("reply_count") or 0) > 0 \
            and not snapshot.get("has_degraded")
    if action.id == "agents-presentation":
        return bool(snapshot.get("has_download") or snapshot.get("has_template")) \
            and not snapshot.get("has_degraded")
    return bool(snapshot.get("answer")) and not snapshot.get("has_degraded")


def _verdict(record: dict) -> tuple[str, list[str]]:
    """Name one record's verdict and the rules it failed.

    A missing optional control is ``absent``; a missing required control is
    ``not met``. A present control is ``met`` only when the early wait, the
    ten-second line, and the result all hold.
    """
    if not record.get("present"):
        if record.get("required"):
            return "not met", ["the required control is absent"]
        return "absent", []
    early = record.get("early") or {}
    late = record.get("late") or {}
    result = record.get("result") or {}
    failures = []
    if not early.get("busy"):
        failures.append("early: the control is not busy")
    if not early.get("pending"):
        failures.append("early: no placeholder is visible")
    if not early.get("same_shape"):
        failures.append("early: the placeholder has no shaped wire lines")
    if not str(early.get("phase") or "").strip():
        failures.append("early: no phase line")
    if early.get("slow"):
        failures.append("early: the ten-second line appeared too soon")
    if not late.get("busy"):
        failures.append("late: the control stopped being busy")
    if not late.get("pending"):
        failures.append("late: no placeholder after ten seconds")
    if not late.get("slow"):
        failures.append("late: no longer-than-usual line")
    if not result.get("ok"):
        failures.append("result: no successful result")
    if result.get("pending"):
        failures.append("result: the placeholder is still visible")
    if not result.get("idle"):
        failures.append("result: the control is still busy")
    return ("met" if not failures else "not met"), failures


def _counts(records: list[dict]) -> dict:
    """Count the three verdicts in a record list."""
    counted = {"met": 0, "not met": 0, "absent": 0}
    for record in records:
        status = str(record.get("status") or "")
        if status in counted:
            counted[status] += 1
    return counted


def _metric_line(records: list[dict]) -> str:
    """The one parsed summary line the parent run prints."""
    counted = _counts(records)
    return (f"METRIC actions={len(records)} met={counted['met']} "
            f"not-met={counted['not met']} absent={counted['absent']}")


def _relative_records(records: list[dict], run_dir: Path) -> list[dict]:
    """Copy the records with photo paths relative to the run folder."""
    copied = json.loads(json.dumps(records))
    prefix = str(run_dir)
    for record in copied:
        photos = record.get("photos") or {}
        for key, value in list(photos.items()):
            if value:
                photos[key] = str(value).replace("\\", "/")
                if not photos[key].startswith("photos/"):
                    photos[key] = photos[key].replace(prefix.replace("\\", "/") + "/", "")
    return copied


def _manifest(records: list[dict], meta: dict) -> dict:
    """The manifest document: meta, every action record, counts and verdict."""
    counted = _counts(records)
    return {
        "tool": "feedback_walkthrough",
        "version": 1,
        "meta": meta,
        "actions": records,
        "counts": counted,
        "verdict": "pass" if counted["not met"] == 0 else "fail",
    }


def _photo(page, action: Action, phase: str, run_dir: Path) -> str:
    """Take one full-page photograph and return its path, or "" on failure."""
    path = run_dir / "photos" / f"{action.id}-{phase}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(path), full_page=True, timeout=20000)
        return str(path)
    except Exception:  # noqa: BLE001 - a photo failure must not stop the walk
        return ""


def _wait_snapshot(page, action: Action, timeout_ms: int) -> dict:
    """Poll until the action's result is on screen, returning the last snapshot."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            snapshot = _snapshot(page, action)
            last = snapshot
            if _result_ready(action, snapshot):
                return snapshot
        except Exception:  # noqa: BLE001 - navigation briefly removes the document
            pass
        page.wait_for_timeout(250)
    return last


def _click_now(locator) -> None:
    """Click without waiting for a navigation, so the pending page is visible."""
    try:
        locator.evaluate(
            """(el) => {
              el.scrollIntoView({block: 'center', inline: 'center'});
              el.click();
            }""")
    except Exception:
        locator.click(timeout=5000, no_wait_after=True)


def _settle(page, action: Action) -> None:
    """Wait for the page's first render and, for the dashboard, its data."""
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(800)
    if action.route == "/":
        try:
            page.wait_for_selector(".cmd-send", state="visible", timeout=15000)
        except Exception:  # noqa: BLE001 - the trigger check reports the absence
            pass


def _run_action(page, base: str, action: Action, run_dir: Path) -> dict:
    """Visit one action, photograph its three states and record the verdict."""
    record = {
        "id": action.id,
        "title": action.title,
        "route": action.route,
        "mode": action.mode,
        "required": action.required,
        "present": False,
        "status": "not met",
        "reason": "",
        "trigger": {},
        "early": {},
        "late": {},
        "result": {},
        "photos": {"early": "", "late": "", "result": ""},
        "failures": [],
    }
    try:
        page.goto(base + action.route, wait_until="domcontentloaded", timeout=30000)
        _settle(page, action)
        trigger = _locator_for(page, action)
        if trigger is None:
            record["status"] = "not met" if action.required else "absent"
            record["reason"] = action.absent_reason
            record["failures"] = (["the required control is absent"]
                                  if action.required else [])
            return record
        record["present"] = True
        record["trigger"] = _element_facts(trigger)
        _mark(page, action, trigger)
        if action.fill_selector:
            page.fill(action.fill_selector, action.fill_text)
        if action.mode == "server":
            page.evaluate(BLOCK_SUBMIT_JS)
        _click_now(trigger)
        page.wait_for_timeout(EARLY_MS)
        early = _snapshot(page, action)
        record["early"] = _facts(early)
        record["photos"]["early"] = _photo(page, action, "early", run_dir)

        remaining = max(0, LATE_MS - EARLY_MS)
        page.wait_for_timeout(remaining)
        late = _snapshot(page, action)
        record["late"] = _facts(late)
        record["photos"]["late"] = _photo(page, action, "late", run_dir)

        if action.mode == "server":
            page.reload(wait_until="domcontentloaded", timeout=30000)
            _settle(page, action)
            trigger = _locator_for(page, action)
            if trigger is None:
                record["status"] = "not met"
                record["failures"] = ["the control vanished before the result"]
                return record
            _mark(page, action, trigger)
            if action.fill_selector:
                page.fill(action.fill_selector, action.fill_text)
            try:
                with page.expect_navigation(timeout=RESULT_TIMEOUT_MS, wait_until="load"):
                    _click_now(trigger)
            except audit.PlaywrightTimeoutError:
                pass

        result = _wait_snapshot(page, action, RESULT_TIMEOUT_MS)
        record["result"] = _facts(result)
        record["result"]["ok"] = _result_ok(action, result)
        record["photos"]["result"] = _photo(page, action, "result", run_dir)
        status, failures = _verdict(record)
        record["status"] = status
        record["failures"] = failures
    except Exception as exc:  # noqa: BLE001 - one action cannot stop the walk
        record["status"] = "not met"
        record["failures"] = [f"{type(exc).__name__}: {exc}"[:300]]
    return record


def _save_mock_connection(context, base: str, mock_port: int) -> None:
    """Save a connection to the loopback mock; the fake keychain holds its key."""
    response = context.request.post(
        base + "/api/connections",
        form={
            "provider": "custom",
            "label": "Feedback walkthrough mock",
            "baseUrl": f"http://127.0.0.1:{mock_port}/v1",
            "apiKey": "sk-local",
            "model": "mock-chat",
        },
        max_redirects=0,
        timeout=60000,
    )
    if response.status not in (200, 201, 303):
        raise audit.AuditError(
            f"the mock connection save answered {response.status}: {response.text()[:200]}")


def _walk(args, run_dir: Path) -> tuple[list[dict], dict]:
    """Boot the isolated desk, run the actions, and return records and meta."""
    tmp_root = Path(tempfile.mkdtemp(prefix="agentdesk-feedback-"))
    mock = None
    desk = None
    browser = None
    records: list[dict] = []
    started = time.monotonic()
    meta = {
        "started_at": _now_iso(),
        "mock_delay_ms": int(args.mock_delay_ms),
        "early_ms": EARLY_MS,
        "late_ms": LATE_MS,
        "result_timeout_ms": RESULT_TIMEOUT_MS,
        "viewport": VIEWPORT,
        "conditions": "full",
        "notes": [],
    }
    try:
        mock, mock_port = audit._start_mock(int(args.mock_delay_ms))
        audit._pin_environment(tmp_root / "data", "full", mock_port)
        if "src" not in sys.path:
            sys.path.insert(0, str(ROOT / "src"))
        if "tools" not in sys.path:
            sys.path.insert(0, str(ROOT / "tools"))
        desk = audit._boot_desk("full", tmp_root)
        meta["base"] = desk["base"]
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=VIEWPORT, device_scale_factor=1, reduced_motion="reduce")
            page = context.new_page()
            page.clock.install(time=FIXED_TIME)
            page.clock.set_fixed_time(FIXED_TIME)
            page.goto(desk["base"] + "/auth/" + desk["token"],
                      wait_until="domcontentloaded", timeout=30000)
            if page.url.rstrip("/") != desk["base"].rstrip("/"):
                raise audit.AuditError(f"auth landed on {page.url}, not the dashboard")
            notes = audit._seed(context, desk["base"], "full", tmp_root)
            meta["notes"].extend(notes)
            _save_mock_connection(context, desk["base"], mock_port)
            meta["notes"].append("mock connection saved")
            wanted = str(getattr(args, "only", "") or "")
            for action in ACTIONS:
                if wanted and action.id != wanted:
                    continue
                record = _run_action(page, desk["base"], action, run_dir)
                records.append(record)
                print(f"[{record['status']}] {action.id}: {action.title}", flush=True)
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - close everything that opened
                pass
        if desk is not None:
            errors = audit._stop_desk(desk)
            if errors:
                meta["notes"].extend(f"stop: {error}" for error in errors)
        if mock is not None:
            try:
                mock.shutdown()
                mock.server_close()
            except Exception:  # noqa: BLE001 - the desk is already gone
                pass
        shutil.rmtree(tmp_root, ignore_errors=True)
        meta["elapsed_s"] = round(time.monotonic() - started, 3)
        meta["finished_at"] = _now_iso()
    return records, meta


def _write_json(path: Path, document) -> None:
    """Write one JSON document with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Parse the options, run the walk and print its verdict."""
    parser = argparse.ArgumentParser(
        description="Walk the desk's model-backed actions and photograph their feedback.")
    parser.add_argument("--out", default=str(DEFAULT_OUT),
                        help="output base directory")
    parser.add_argument("--mock-delay-ms", type=int, default=DEFAULT_DELAY_MS,
                        help="the mock model's delay (default 12000)")
    parser.add_argument("--only", default="",
                        help="run one action id from the plan")
    args = parser.parse_args(argv)
    if args.only and args.only not in {action.id for action in ACTIONS}:
        parser.error(f"unknown action id: {args.only}")
    if audit.sync_playwright is None:
        print(audit.PLAYWRIGHT_HELP)
        return 2
    run_dir = Path(args.out) / _now_stamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run {run_dir}", flush=True)
    print(f"mock delay {args.mock_delay_ms} ms; full condition; 1280 px", flush=True)
    try:
        records, meta = _walk(args, run_dir)
    except Exception as exc:  # noqa: BLE001 - print the cause and keep the folder
        print(f"walkthrough failed: {type(exc).__name__}: {exc}")
        return 2
    relative = _relative_records(records, run_dir)
    document = _manifest(relative, meta)
    _write_json(run_dir / "manifest.json", document)
    for record in records:
        reason = ("; ".join(record["failures"]) if record["failures"]
                  else record.get("reason", ""))
        print(f"{record['id']}: {record['status']}"
              + (f" ({reason[:200]})" if reason else ""), flush=True)
    print(_metric_line(records), flush=True)
    return 0 if document["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
