"""CLI wiring tests: argument parsing and the serve call, without blocking.

`main` is thin on purpose; these tests pin its contract (defaults, the
--no-browser path) by watching create_server and serve instead of
building real stores.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot import config
from nexuusbot.server import cli


def _no_personal_config(monkeypatch, tmp_path):
    """Point the config-file loader at a file this test owns (absent).

    The real loader writes ~/.agent-desk/config.env into os.environ for
    the rest of the process, so a developer whose config sets
    AGENTDESK_MAIL_FOLDER would leak it into every later test: the mail
    watcher's folder fallback reads it, and a toggle-on poll would file
    cards from the developer's own sample folder. An absent file is the
    loader's own no-op path, so main still runs its real wiring.
    """
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "no-config.env")


def test_defaults_open_the_browser_and_pick_the_port():
    args = cli.build_parser().parse_args([])
    assert args.port is None
    assert args.no_browser is False


def test_port_and_no_browser_flags_parse():
    args = cli.build_parser().parse_args(["--port", "9000", "--no-browser"])
    assert args.port == 9000
    assert args.no_browser is True


def test_main_builds_a_loopback_server_and_honors_no_browser(monkeypatch, tmp_path):
    _no_personal_config(monkeypatch, tmp_path)
    calls = {}

    def fake_create_server(*args, **kwargs):
        calls["host"] = kwargs.get("host", args[0] if args else None)
        calls["port"] = kwargs.get("port")

        class FakeServer:
            pass

        return FakeServer()

    def fake_serve(server, open_browser):
        calls["open_browser"] = open_browser

    monkeypatch.setattr(cli.app, "create_server", fake_create_server)
    monkeypatch.setattr(cli.app, "serve", fake_serve)
    assert cli.main(["--no-browser"]) == 0
    assert calls["host"] in ("127.0.0.1", None)
    assert calls["port"] is None
    assert calls["open_browser"] is False


def test_main_defaults_to_opening_the_browser(monkeypatch, tmp_path):
    _no_personal_config(monkeypatch, tmp_path)
    calls = {}

    def fake_create_server(*args, **kwargs):
        class FakeServer:
            pass

        return FakeServer()

    def fake_serve(server, open_browser):
        calls["open_browser"] = open_browser

    monkeypatch.setattr(cli.app, "create_server", fake_create_server)
    monkeypatch.setattr(cli.app, "serve", fake_serve)
    assert cli.main([]) == 0
    assert calls["open_browser"] is True


def test_main_loads_the_config_file_before_building_the_server(monkeypatch):
    order = []

    def fake_load():
        order.append("config")

    def fake_create_server(*args, **kwargs):
        order.append("server")

        class FakeServer:
            pass

        return FakeServer()

    def fake_serve(server, open_browser):
        pass

    monkeypatch.setattr(cli, "load_env_file", fake_load)
    monkeypatch.setattr(cli.app, "create_server", fake_create_server)
    monkeypatch.setattr(cli.app, "serve", fake_serve)
    assert cli.main(["--no-browser"]) == 0
    assert order == ["config", "server"]  # the bridge and the llm see the file
