"""One end-to-end smoke over the real registry checkout.

Boots the real server over a temp data directory, installs
sales-delta-widget 0.1.0 from this worktree's own registry through the
HTTP API, with a real .xlsx in the workspace the plugin's glob
resolves, and reads the bound card back. Not part of the suite: run
directly (python tools/smoke_first_plugin.py) from the worktree root.
"""
import json
import os
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from excel_fixtures import make_xlsx  # noqa: E402


def main() -> int:
    """Run the end-to-end registry install smoke and return the exit code.

    Boots the real server on an ephemeral port over a temporary AGENTDESK_DATA
    directory, seeds workspace/reports/sales.xlsx, installs sales-delta-widget
    from this checkout's registry over HTTP, and checks that the dashboard
    card binds a fresh payload. Prints the registry, install, card and record
    lines, then "SMOKE PASS". An unmet assertion or an HTTP error exits
    nonzero with its traceback; the temporary directory is removed either
    way, so the checkout keeps nothing.
    """
    # ignore_cleanup_errors: the app's audit store holds its sqlite file
    # open until process exit (shutdown does not close it); Windows then
    # refuses the temp-dir delete. The check is done by then.
    with tempfile.TemporaryDirectory(prefix="agentdesk-smoke-",
                                     ignore_cleanup_errors=True) as tmp:
        os.environ["AGENTDESK_DATA"] = tmp
        # Import late: the data dir must be set first.
        from agentdesk.server import app as server_app

        reports = Path(tmp) / "workspace" / "reports"
        reports.mkdir(parents=True)
        (reports / "sales.xlsx").write_bytes(make_xlsx([
            ["Region", "Sales"], ["North", 10], ["South", 20],
        ]))

        server = server_app.create_server(port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.port}"

        # Bootstrap a session like the launcher does.
        token = server.sessions.bootstrap_token()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(f"{base}/auth/{token}", timeout=5)

        def post(path: str, payload: dict) -> dict:
            """POST a JSON payload as the bootstrapped session and return the reply.

            Goes through the same cookie jar as the token exchange, so it is
            authenticated; a non-2xx answer raises urllib.error.HTTPError rather than
            being inspected.
            """
            request = urllib.request.Request(
                base + path, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with opener.open(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))

        def get(path: str) -> dict:
            """GET one JSON document as the bootstrapped session and decode it.

            Shares the cookie jar created after the token exchange; a non-2xx answer
            raises, so the assertions live at the call sites.
            """
            with opener.open(base + path, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))

        listing = get("/api/registry")
        assert listing["ok"], listing
        entry = listing["plugins"][0]
        print(f"registry: {entry['id']} {entry['latest']} "
              f"risk={entry['risk']} class={entry['class']} "
              f"origin={listing['origin']}")

        result = post("/api/registry/install", {"id": "sales-delta-widget"})
        assert result.get("ok"), result
        print(f"installed: {result['id']}@{result['version']} "
              f"sha256={result['sha256'][:12]} pilot={result['pilot']}")

        dashboard = get("/api/dashboard")
        cards = dashboard["plugins"]["cards"]
        assert cards, "no plugin card on the dashboard"
        card = cards[0]
        print(f"card: {card['title']} v{card['version']} "
              f"freshness={card['freshness']} pilot={card['pilot']}")
        payload = card["payload"]
        assert payload, "no bound payload on the card"
        for element in payload["elements"]:
            shown = element.get("value") or element.get("text")
            label = element.get("label", "")
            print(f"  {element['kind']}: {shown}" + (f" ({label})" if label else ""))
        assert payload["status"] == "fresh"
        values = [e.get("value") for e in payload["elements"]]
        assert any("First snapshot" in v for v in values if v), values

        record = get("/api/plugins")["plugins"][0]
        source = record["data_source"]
        print(f"record: reading {source.get('file')} "
              f"status={source['status']}")

        # Detach the data source before shutdown so Windows lets the
        # temp data directory go (the store file closes with the watch).
        post("/api/plugins/sales-delta-widget/disable", {})
        server.shutdown()
        server.server_close()
        print("SMOKE PASS")
        return 0


if __name__ == "__main__":
    sys.exit(main())
