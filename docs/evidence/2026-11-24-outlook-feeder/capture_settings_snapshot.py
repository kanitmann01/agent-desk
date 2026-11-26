"""Capture the Settings Outlook alerts block without launching a browser.

Two boots of the real server over the test harness: one with the feed
off (the default), and one with a watcher whose injected alert pass
reports the manual fallback. The script writes the captured API payloads
and the extracted alerts block HTML into this evidence folder.

Usage (from the repository root):
    python docs/evidence/2026-11-24-outlook-feeder/capture_settings_snapshot.py
"""

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for _path in (str(ROOT / "src"), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import server_harness
from server_harness import Booted

from agentdesk.inbox.store import InboxStore
from agentdesk.mail.store import MailStore
from agentdesk.mail.watcher import MailWatch

OUT = Path(__file__).resolve().parent
START = "<h3>Outlook alerts</h3>"
END = "</section>"


def alerts_block(page: str) -> str:
    """The Outlook alerts block, from its heading to the Sources close tag."""
    start = page.index(START)
    end = page.index(END, start)
    return page[start:end] + END + "\n"


def watch_with_feeder(folder: Path, feeder):
    """A real watcher over in-memory stores, with the alert pass injected."""
    folder.mkdir(parents=True, exist_ok=True)
    return MailWatch(
        inbox=InboxStore(
            sqlite3.connect(":memory:", check_same_thread=False), lambda: 0.0),
        store=MailStore(
            sqlite3.connect(":memory:", check_same_thread=False), lambda: 0.0),
        folder_provider=lambda: str(folder),
        feeder=feeder,
    )


def feed_off():
    booted = Booted()
    try:
        auth = booted.exchange()
        status, _headers, body = booted.request("GET", "/widgets/settings", auth)
        payload = json.loads(body)
        (OUT / "settings-widgets-off.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        page = booted.request("GET", "/settings", auth)[2].decode("utf-8")
        block = alerts_block(page)
        (OUT / "settings-alerts-off.html").write_text(block, encoding="utf-8")
        print("feed off: GET /widgets/settings status", status)
        print("feed off: mail_feeder =", payload.get("mail_feeder"))
        print("feed off: alerts block bytes =", len(block))
        print("feed off: block says 'Not run yet':", "Not run yet" in block)
        print("feed off: block says 'Alerts only, not a mailbox':",
              "Alerts only, not a mailbox" in block)
    finally:
        booted.close()


def manual_fallback():
    def feeder():
        return {
            "collector": "manual",
            "platform": "win32",
            "lastRunTs": 1700000000.0,
            "lastResult": "unavailable",
            "lastError": (
                "No automatic Outlook collector is available on this machine."
                " Save the messages you want with Save as into the mail folder,"
                " and the desk will read them."
            ),
            "written": 0,
            "coverageFromTs": None,
            "coverageToTs": None,
        }

    with tempfile.TemporaryDirectory(prefix="agentdesk-evidence-mail-") as temp:
        booted = Booted(mail=watch_with_feeder(Path(temp) / "mail", feeder))
        try:
            auth = booted.exchange()
            status, _headers, body = booted.post_json(
                "/settings/mail/fetch-now", {}, auth)
            payload = json.loads(body)
            (OUT / "settings-fetch-manual.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
            page = booted.request("GET", "/settings", auth)[2].decode("utf-8")
            block = alerts_block(page)
            (OUT / "settings-alerts-manual.html").write_text(block, encoding="utf-8")
            print("manual fallback: POST /settings/mail/fetch-now status", status)
            print("manual fallback: ran =", payload.get("ran"),
                  "collector =", payload["fetch"].get("collector"),
                  "lastResult =", payload["fetch"].get("lastResult"))
            print("manual fallback: alerts block bytes =", len(block))
            print("manual fallback: names the manual folder source:",
                  "manual .eml folder above is the mail source" in block)
            print("manual fallback: shows an alert count:",
                  "0 alerts" in block or "1 alert" in block)
        finally:
            booted.close()


if __name__ == "__main__":
    feed_off()
    print()
    manual_fallback()
