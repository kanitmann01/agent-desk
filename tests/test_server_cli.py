"""CLI wiring tests: argument parsing and the serve call, without blocking.

`main` is thin on purpose; these tests pin its contract (defaults, the
--no-browser path) by watching the serve call instead of serving.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.server import cli


def test_defaults_open_the_browser_and_pick_the_port():
    args = cli.build_parser().parse_args([])
    assert args.port is None
    assert args.no_browser is False


def test_port_and_no_browser_flags_parse():
    args = cli.build_parser().parse_args(["--port", "9000", "--no-browser"])
    assert args.port == 9000
    assert args.no_browser is True


def test_main_builds_a_loopback_server_and_honors_no_browser(monkeypatch):
    calls = {}

    def fake_serve(server, open_browser):
        calls["host"] = server.server_address[0]
        calls["open_browser"] = open_browser

    monkeypatch.setattr(cli.app, "serve", fake_serve)
    assert cli.main(["--no-browser"]) == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["open_browser"] is False


def test_main_defaults_to_opening_the_browser(monkeypatch):
    calls = {}

    def fake_serve(server, open_browser):
        calls["open_browser"] = open_browser
        server.server_close()

    monkeypatch.setattr(cli.app, "serve", fake_serve)
    assert cli.main([]) == 0
    assert calls["open_browser"] is True
