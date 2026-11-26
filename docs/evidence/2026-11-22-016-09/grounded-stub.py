# Note (2026-11-25): the sample client's name in this evidence record was
# replaced with the fictional sample name (Harborlight) on 2026-11-25.
"""The evidence stub for the 016-09 browser walkthrough.

An OpenAI-compatible /chat/completions mock that answers the
profile-review prompt with exactly one grounded add: it parses the
activity JSON the desk appends to the prompt, cites the newest two
activity ids, and returns the ticket's example line. Any other prompt
gets a plain non-JSON sentence (which the apply gate refuses, proving
the gate in the same session). Loopback only, throwaway session only.

Run: python docs/evidence/2026-11-22-016-09/grounded-stub.py [port]
"""

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LINE = "Owns the Harborlight Freight and Kestrel Foods accounts."


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 - the stdlib's spelling
        if self.path.rstrip("/") not in ("/v1/chat/completions",
                                         "/chat/completions"):
            self._send(404, {"error": "the stub serves /chat/completions"})
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt = body["messages"][0]["content"]
        reply = self._grounded_add(prompt)
        self._send(200, {
            "choices": [{"message": {"role": "assistant",
                                     "content": reply}}],
        })

    @staticmethod
    def _grounded_add(prompt: str) -> str:
        # The desk appends the input payload as JSON on its own line.
        payload = None
        for match in re.finditer(r"\{.*\}", prompt, re.DOTALL):
            try:
                parsed = json.loads(match.group(0))
            except ValueError:
                continue
            if isinstance(parsed, dict) and "activity" in parsed:
                payload = parsed
        if payload is None or not payload.get("activity"):
            return "The stub answers a plain prompt with this sentence."
        ids = [row["id"] for row in payload["activity"]
               if isinstance(row.get("id"), int)]
        return json.dumps({"ops": [
            {"op": "add", "text": LINE, "from": sorted(ids)[-2:]},
        ]})

    def _send(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
