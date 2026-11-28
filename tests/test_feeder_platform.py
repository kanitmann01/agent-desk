"""The platform seam: each host gets its own reader, or the manual fallback.

The core must import on any machine, so the platform decision is data,
not an import: default_collectors takes the platform label and returns
the reader for that label alone, so the reader's own unavailable cause
survives into the status. Only a platform with no reader gets the manual
fallback. Only this module names a reader class; the contract, the
writer and the runner do not.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.feeder import (
    MailCollector,
    OutlookFeeder,
    UnavailableCollector,
    default_collectors,
    render_eml,
    write_mail,
    write_status,
)
from nexuusbot.feeder.collectors.mac_notifications import MacNotificationCollector
from nexuusbot.feeder.collectors.wpn import WpnCollector
from nexuusbot.feeder.contract import MANUAL_CAUSE
from nexuusbot.feeder.platform import current_platform

FEEDER_SRC = ROOT / "src" / "nexuusbot" / "feeder"
CORE_FILES = ["__init__.py", "contract.py", "writer.py", "runner.py"]
PLATFORM_READERS = {
    "win32api", "win32com", "winreg", "AppKit", "Foundation", "objc",
}


def imported_roots(path: Path) -> set[str]:
    """The top-level modules one source file imports, relative imports aside."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def imported_modules(path: Path) -> set[str]:
    """The full module names one source file imports, relative imports aside."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def assert_manual_fallback(collector) -> None:
    """The collector is the manual fallback, unavailable with its cause."""
    assert isinstance(collector, UnavailableCollector)
    assert isinstance(collector, MailCollector)
    assert collector.name == "manual"
    available, cause = collector.available()
    assert available is False
    assert cause == MANUAL_CAUSE
    assert "Save as" in cause


def test_default_collectors_on_win32_is_the_wpn_reader_only():
    collectors = default_collectors("win32")
    assert isinstance(collectors, tuple)
    assert [collector.name for collector in collectors] == ["wpn"]
    (wpn,) = collectors
    assert isinstance(wpn, WpnCollector)
    assert isinstance(wpn, MailCollector)


def test_default_collectors_on_darwin_is_the_mac_reader_only():
    collectors = default_collectors("darwin")
    assert isinstance(collectors, tuple)
    assert [collector.name for collector in collectors] == ["mac-notifications"]
    (mac,) = collectors
    assert isinstance(mac, MacNotificationCollector)
    assert isinstance(mac, MailCollector)


def test_default_collectors_on_other_platforms_is_the_manual_fallback():
    for label in ("linux", "freebsd", "cygwin"):
        collectors = default_collectors(label)
        assert isinstance(collectors, tuple)
        assert len(collectors) == 1
        assert_manual_fallback(collectors[0])


def test_default_collectors_uses_this_host_when_no_label_is_given():
    assert current_platform() == sys.platform
    expected = {
        "win32": ["wpn"],
        "darwin": ["mac-notifications"],
    }.get(sys.platform, ["manual"])
    collectors = default_collectors()
    assert [collector.name for collector in collectors] == expected
    for collector in collectors:
        assert isinstance(collector, MailCollector)
    if sys.platform not in ("win32", "darwin"):
        assert_manual_fallback(collectors[-1])


def test_the_package_reexports_the_public_seam():
    assert MailCollector is not None
    assert OutlookFeeder.__name__ == "OutlookFeeder"
    assert UnavailableCollector is not None
    assert callable(default_collectors)
    assert callable(render_eml)
    assert callable(write_mail)
    assert callable(write_status)


def test_the_core_files_import_without_a_platform_reader_module():
    """No core feeder module needs winreg, win32com, AppKit or the OS platform."""
    for name in CORE_FILES:
        roots = imported_roots(FEEDER_SRC / name)
        assert not roots & PLATFORM_READERS, name
        assert "platform" not in roots, name  # our own .platform import is relative


def test_only_the_platform_module_imports_a_reader():
    """The platform seam is the one place the two readers are wired in."""
    for name in CORE_FILES:
        modules = imported_modules(FEEDER_SRC / name)
        assert not any(
            module.startswith("nexuusbot.feeder.collectors") for module in modules
        ), name
    platform_modules = imported_modules(FEEDER_SRC / "platform.py")
    assert "nexuusbot.feeder.collectors.wpn" in platform_modules
    assert "nexuusbot.feeder.collectors.mac_notifications" in platform_modules
