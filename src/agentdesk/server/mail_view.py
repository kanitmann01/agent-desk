"""The mail page: the digest, the follow-ups, the reply drafts.

Server-rendered no-JS like the memory page: everything escaped, every
action a plain POST that lands back on the page. The metadata-only rule
is visible in the page's own copy: it shows headers (from, to, subject,
date, thread), and each message's Draft reply form is a textarea the
USER types into. The page never displays or edits message bodies,
because the app never read them.
"""

import html
from urllib.parse import quote

from agentdesk.server.pages import page_shell
from agentdesk.mail.core import format_header_ts
from agentdesk.mail.watcher import STATE_ERROR


def _off_page(version: str, off_reason: str, inbox_count: int = 0) -> str:
    """The whole page for the mail toggle being off, with the reason it is off.

    The reason is escaped and shown as the body; the rest of the copy says what the page
    would show and what it reads, so the off state still explains the feature.
    """
    esc_reason = html.escape(off_reason)
    content = f"""<h1>Mail</h1>
<div class="widget" id="mail-off">
<div class="w-head"><h2>Mail digest is off</h2></div>
<p>{esc_reason}</p>
<p>When it is on, this page shows a digest of the threads active in the
last 24 hours, threads waiting on you, and a reply draft box per
message. It reads only the headers of the .eml files in a folder you
choose (From, To, Cc, Subject, Date, Message-ID, In-Reply-To); message
bodies are discarded at parse time, nothing is sent to any model, and
nothing leaves this machine.</p>
<p><a href="/settings">Turn it on in settings</a> (the mail toggle, plus
the folder it watches).</p>
</div>"""
    return page_shell("Mail", "/mail", content, version, inbox_count=inbox_count)


def _status_line(view: dict) -> str:
    """The one-line folder status: path, message count and the follow-up threshold.

    A watcher error replaces the threshold sentence with its cause, so a failing folder
    never reads as a working one.
    """
    folder = html.escape(view.get("folder") or "")
    count = len(view.get("messages") or [])
    days = html.escape(str(view.get("followUpDays", "")))
    # The raw state against the watcher's own constant; only the words
    # that reach the page are escaped.
    if view.get("state") == STATE_ERROR:
        cause = html.escape(view.get("cause") or "")
        return (
            f"<p class='origin-why' id='mail-status'>Folder: <span class='mono'>{folder}</span>, "
            f"{count} messages, error: {cause}</p>"
        )
    return (
        f"<p class='origin-why' id='mail-status'>Folder: <span class='mono'>{folder}</span>, "
        f"{count} messages read (headers only). Follow-up threshold: {days} days "
        "without a message from you.</p>"
    )


def _retest_form() -> str:
    """The no-JS form that asks the server to re-read the watched folder now."""
    return (
        "<form method='post' action='/mail/retest' class='cardform'>"
        "<button class='btn btn-secondary' type='submit'>Check the folder now</button>"
        "</form>"
    )


def _digest_section(view: dict) -> str:
    """The "active in the last 24 hours" section, or its empty state.

    One line per digest entry: thread, message count, and the last sender and its
    formatted header time.
    """
    digest = view.get("digest") or []
    if not digest:
        return (
            "<h2>Active in the last 24 hours</h2>"
            "<p class='empty' id='mail-digest-empty'>No thread has seen a message in "
            "the last 24 hours, so there is no digest.</p>"
        )
    rows = "".join(
        f"<div class='ask'><b>{html.escape(d['thread'])}</b> "
        f"<span class='empty'>{d['count']} message(s), last from "
        f"{html.escape(d['lastFrom'])} at {format_header_ts(d['lastTs'])}</span></div>"
        for d in digest
    )
    return f"<h2>Active in the last 24 hours</h2>{rows}"


def _followups_section(view: dict) -> str:
    """The "waiting on you" section, or its empty state.

    Each entry is indexed as followup-<n> for the client and names the view's follow-up
    threshold, so the page states why the thread is listed.
    """
    follow_ups = view.get("followUps") or []
    days = html.escape(str(view.get("followUpDays", "")))
    if not follow_ups and view.get("selfDetection") is False:
        return (
            "<h2>Waiting on you</h2>"
            "<p class='empty' id='mail-followups-off'>Mail self-detection is off "
            "because no address is set, so this desk cannot know which threads "
            "you already answered and files no follow-up cards. Save your own "
            "address in <a href='/settings'>settings</a> to turn it on.</p>"
        )
    if not follow_ups:
        return (
            "<h2>Waiting on you</h2>"
            "<p class='empty' id='mail-followups-empty'>Nothing is waiting: every "
            f"thread either saw a message from you in the last {days} days, or is "
            "marked handled below.</p>"
        )
    rows = "".join(
        f"<div class='ask' id='followup-{i}'><b>{html.escape(f['thread'])}</b> "
        f"<span class='empty'>last from {html.escape(f['from'])} at "
        f"{format_header_ts(f['dateTs'])}; {days} days passed with no reply from "
        "you. Decide the card in the inbox (either way) to mark it handled.</span></div>"
        for i, f in enumerate(follow_ups)
    )
    return f"<h2>Waiting on you</h2>{rows}"


def _message_rows(view: dict) -> str:
    """One card per message: its headers, an optional Cc line, and a reply draft form.

    The message id is percent-encoded before it is escaped, so an id with a slash or
    space still reaches /mail/<id>/draft intact. The textarea starts empty: the draft is
    the user's own words, and the body was never read.
    """
    messages = view.get("messages") or []
    if not messages:
        return (
            "<h2>Messages</h2>"
            "<p class='empty' id='mail-messages-empty'>No .eml files in the folder "
            "yet. Drop some in and check the folder again.</p>"
        )
    rows = []
    for message in messages:
        target = quote(message.id, safe="")
        cc = html.escape(message.cc) if message.cc else ""
        cc_line = f"<span class='empty'>Cc: {cc}</span> " if cc else ""
        rows.append(
            f"<article class='widget' id='message-{html.escape(target)}'>"
            "<div class='w-head'>"
            f"<span class='origin-line'>{html.escape(message.thread)}</span>"
            f"<span class='stamp'>{html.escape(format_header_ts(message.date_ts))}</span></div>"
            f"<h3>{html.escape(message.subject)}</h3>"
            f"<p>From {html.escape(message.sender)} to {html.escape(message.to)}. "
            f"{cc_line}<span class='empty'>Headers only; the body was never read.</span></p>"
            f"<form method='post' action='/mail/{html.escape(target)}/draft' class='cardform'>"
            f"<label class='empty' for='draft-{html.escape(target)}'>Draft reply (your own words; "
            "recipients and subject come from the headers)</label>"
            f"<textarea id='draft-{html.escape(target)}' name='body' rows='3' "
            "placeholder='Type the reply you want to send.'></textarea>"
            "<button class='btn btn-primary' type='submit'>Draft reply</button>"
            "</form>"
            "</article>"
        )
    return f"<h2>Messages</h2>{''.join(rows)}"


def _handled_section(view: dict) -> str:
    """The "handled" section: the thread names marked handled, or its empty state."""
    handled = view.get("handled") or []
    if not handled:
        return (
            "<h2>Handled</h2>"
            "<p class='empty' id='mail-handled-empty'>No thread is marked handled "
            "yet. Deciding a follow-up card in the inbox marks its thread.</p>"
        )
    rows = "".join(
        f"<div class='ask'><b>{html.escape(name)}</b> "
        "<span class='empty'>marked handled; follow-ups stay quiet</span></div>"
        for name in handled
    )
    return f"<h2>Handled</h2>{rows}"


def render_mail_page(version: str, view: dict | None, off_reason: str = "", inbox_count: int = 0) -> str:
    """The full mail document: off state, or the live digest view."""
    if view is None:
        return _off_page(version, off_reason, inbox_count)
    content = f"""<h1>Mail</h1>
<p>A metadata-only digest of the folder you chose: thread names, senders
and dates. Message bodies are discarded the moment the file is read;
nothing goes to any model; reply drafts contain the words you type
here, and accepting one writes a file to your local outbox to send
yourself.</p>
{_status_line(view)}
{_retest_form()}
{_digest_section(view)}
{_followups_section(view)}
{_message_rows(view)}
{_handled_section(view)}"""
    return page_shell("Mail", "/mail", content, version, inbox_count=inbox_count)
