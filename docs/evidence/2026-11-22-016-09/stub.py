# Note (2026-11-25): the sample client's name in this evidence record was
# replaced with the fictional sample name (Harborlight) on 2026-11-25.
"""Loopback chat-completions stub for the ticket 016-09 browser walkthrough.

Three jobs, all honest about the wire:

- a profile-review prompt (the step's own marker sentence) gets one
  grounded add: the line, and the two newest activity ids from the JSON
  payload the desk appended, so the reply can only ever cite ids the desk
  actually showed it;
- any other prompt gets one plain sentence, so the assistant, the desk
  check and every other step degrade the way they would against a model
  that answered in prose.

Every POST is logged (bytes, which marker matched, the cited ids) so the
walkthrough can show exactly what left the machine and that the review
was one call. Nothing is logged from the ask text itself.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROFILE_MARKER = "Only add or patch lines"
LINE = "Owns the Harborlight Freight and Kestrel Foods accounts."
LOG_PATH = sys.argv[2] if len(sys.argv) > 2 else "stub.log"


def _payload(prompt: str) -> dict:
    """The desk appends the input JSON after the prompt; read that block."""
    start = prompt.find('{"activity"')
    if start < 0:
        return {}
    try:
        return json.loads(prompt[start:])
    except ValueError:
        return {}


def _newest_ids(prompt: str) -> list[int]:
    """The two newest activity ids the desk showed, never invented ones."""
    rows = _payload(prompt).get("activity") or []
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    return [i for i in ids if isinstance(i, int)][-2:]


def reply_for(prompt: str) -> str:
    if PROFILE_MARKER in prompt:
        ids = _newest_ids(prompt)
        if not ids:
            return json.dumps({"ops": []})
        return json.dumps({"ops": [
            {"op": "add", "text": LINE, "from": ids},
        ]})
    return "The stub endpoint answers plainly, from no model at all."


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - the stdlib's spelling
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        prompt = str(messages[0].get("content") or "") if messages else ""
        reply = reply_for(prompt)
        marker = "profile-review" if PROFILE_MARKER in prompt else "plain"
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log.write(json.dumps({
                "bytes": len(prompt.encode("utf-8")),
                "marker": marker,
                "cited": _newest_ids(prompt) if marker == "profile-review" else [],
                "learnedIn": [e.get("text") for e in
                              (_payload(prompt).get("learned") or [])],
            }) + "\n")
        data = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": reply}}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802 - the stdlib's spelling
        data = b'{"error": "the stub speaks only to POST /chat/completions"}'
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # noqa: A003 - the log file is the log
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8793
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"stub listening on http://127.0.0.1:{port}/v1", flush=True)
    server.serve_forever()
