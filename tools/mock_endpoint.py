"""A local stand-in for the desk's BYOK endpoint, for demos and tests.

The desk's one model client speaks the OpenAI-compatible chat shape
against any base URL the user saves in settings. This tool is that shape
on the loopback: it answers /chat/completions with deterministic text
built from the prompt, so the full memory loop (run, recall, feedback,
capture, review, recall again) can be demonstrated end to end without a
real key, and the same walkthrough is repeatable on any machine.

It is a test double, not a model. What it does is honest about what the
host sent: an agent prompt's reply echoes the bounded known-facts block
the host injected (so recall is visible in the artifact), and an
extraction prompt's reply returns the user's own feedback sentence as
the fact candidate (what a careful extraction model would pick). The
words are canned; the plumbing they ride is the real one.

Run it, then point the desk's endpoint at http://127.0.0.1:<port>/v1:

    python tools/mock_endpoint.py --port 8788
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The stable markers the reply builder keys on: the extraction system
# prompt's own first sentence, and the agent prompt's instructions label.
_EXTRACTION_MARKER = "durable memory facts"
_AGENT_MARKER = "agent instructions:"
_FEEDBACK_MARKER = "How it landed (the user's own words): "
_BRIEF_MARKER = "The user's brief (they will not restate their context; use it):"
_FACTS_HEADER_MARKER = "Known facts about the user"

# Names the entity miner refuses: sentence starters and calendar words,
# the rules extractor's own stoplist spirit, so "My manager Dana" yields
# Dana alone.
_NOT_NAMES = {
    "i", "we", "you", "they", "he", "she", "it", "my", "our", "the",
    "a", "an", "this", "that", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday", "today", "tomorrow",
    "yesterday", "q1", "q2", "q3", "q4", "the", "and", "but", "so",
}


def _known_facts(prompt: str) -> list[str]:
    """The '- ' fact lines under the known-facts header, in order.

    The host's bounded block is the only channel memory reaches the
    prompt through, so echoing these lines back is echoing exactly what
    the desk recalled for this call.
    """
    facts: list[str] = []
    in_block = False
    for line in prompt.splitlines():
        if _FACTS_HEADER_MARKER in line:
            in_block = True
            continue
        if in_block:
            if not line.strip():
                break
            if line.startswith("- "):
                facts.append(line[2:].strip())
    return facts


def _after(prompt: str, marker: str) -> str:
    """The text after the marker's line, or the empty string."""
    if marker not in prompt:
        return ""
    tail = prompt.split(marker, 1)[1]
    return tail.lstrip(" \n").strip()


def _names_in(sentence: str) -> list[dict]:
    """Capitalized words as person entities, the draft cards' own spirit."""
    seen: list[str] = []
    for word in re.findall(r"[A-Z][a-z]+", sentence):
        if word.lower() in _NOT_NAMES or word in seen:
            continue
        seen.append(word)
    return [{"name": word, "type": "person"} for word in seen]


def _extraction_reply(prompt: str) -> str:
    """One fact candidate: the user's own feedback sentence, verbatim."""
    feedback = ""
    for line in prompt.splitlines():
        if _FEEDBACK_MARKER in line:
            feedback = line.split(_FEEDBACK_MARKER, 1)[1].strip()
            break
    if not feedback:
        return json.dumps({"facts": []})
    fact = {"text": feedback, "kind": "world", "entities": _names_in(feedback)}
    return json.dumps({"facts": [fact]})


def _slides_reply(prompt: str) -> str:
    """A deck-shaped answer that carries the brief and the recalled facts.

    The closing slide exists only when the host injected a known-facts
    block, so a run before feedback has no such slide and a run after
    feedback visibly gains one: recall made visible in the artifact.
    """
    brief = _after(prompt, _BRIEF_MARKER) or "an untitled brief"
    title = " ".join(brief.split())[:60] or "Untitled"
    facts = _known_facts(prompt)
    slides = [
        {"title": "Overview", "bullets": [brief[:200], "Prepared by the Agents surface"]},
        {"title": "Where we are", "bullets": ["The current state, in three lines", "What moved since last time"]},
        {"title": "What changed", "bullets": ["The two changes that matter", "Why they happened now"]},
        {"title": "What we ask for", "bullets": ["The decision needed", "The date it is needed by"]},
    ]
    if facts:
        slides.append({"title": "Grounded in your known facts", "bullets": facts})
    return json.dumps({"title": title, "slides": slides})


def _outline_reply(prompt: str) -> str:
    """A plain-text briefing, for kinds that answer in outlines."""
    brief = _after(prompt, _BRIEF_MARKER) or "an untitled brief"
    facts = _known_facts(prompt)
    lines = [f"Headline: {' '.join(brief.split())[:120]}", "- The watched numbers, read once", "- The one change worth acting on"]
    for fact in facts:
        lines.append(f"- Grounded in your known facts: {fact}")
    return "\n".join(lines)


def reply_for(prompt: str) -> str:
    """The deterministic answer for one prompt, by its stable markers.

    The kind is read from the agent-instructions label, never from loose
    words in the prompt: a recalled fact can itself say "slides", and
    that must not turn a worksheet briefing into a deck.
    """
    if _EXTRACTION_MARKER in prompt:
        return _extraction_reply(prompt)
    if _AGENT_MARKER in prompt:
        if "Worksheet brief agent instructions:" in prompt:
            return _outline_reply(prompt)
        return _slides_reply(prompt)
    return "The mock endpoint answers a plain prompt with this sentence."


class MockEndpointHandler(BaseHTTPRequestHandler):
    """One route, the chat shape the desk's client already parses."""

    def do_POST(self) -> None:  # noqa: N802 - the stdlib's spelling
        """Answer /chat/completions with the deterministic reply."""
        if self.path.rstrip("/") != "/v1/chat/completions" and self.path.rstrip("/") != "/chat/completions":
            self._send_json(404, {"error": "the mock serves /chat/completions only"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        prompt = ""
        if messages and isinstance(messages[0], dict):
            prompt = str(messages[0].get("content") or "")
        reply = reply_for(prompt)
        print(f"mock endpoint: {len(prompt)}-char prompt -> {len(reply)}-char reply", flush=True)
        self._send_json(200, {
            "choices": [{"message": {"role": "assistant", "content": reply}}],
        })

    def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
        """A plain refusal, so a browser visit cannot look like an API call."""
        self._send_json(404, {"error": "the mock speaks only to POST /chat/completions"})

    def _send_json(self, status: int, payload: dict) -> None:
        """One JSON answer with the right length header."""
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003 - the stdlib's hook
        """Stay quiet; the one-line print per request is the whole log."""


def main() -> int:
    """Parse the port, serve until interrupted."""
    parser = argparse.ArgumentParser(description="The desk's local mock BYOK endpoint")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockEndpointHandler)
    print(f"mock endpoint listening on http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
