"""The platform seam: one manual fallback on every host, and a core that
never imports a platform reader.

The core must import on any machine, so the platform decision is data,
not an import: default_collectors takes the platform label and returns
the same honest fallback until the Windows and macOS readers arrive.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.feeder import (
    MailCollector,
    OutlookFeeder,
    UnavailableCollector,
    default_collectors,
    render_eml,
    write_mail,
    write_status,
)
from agentdesk.feeder.contract import MANUAL_CAUSE
from agentdesk.feeder.platform import current_platform

FEEDER_SRC = ROOT / "src" / "agentdesk" / "feeder"
CORE_FILES = ["__init__.py", "contract.py", "writer.py", "runner.py", "platform.py"]
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


def test_default_collectors_returns_the_manual_fallback_on_every_platform():
    for label in ("win32", "darwin", "linux", "freebsd"):
        collectors = default_collectors(label)
        assert isinstance(collectors, tuple)
        assert len(collectors) == 1
        (manual,) = collectors
        assert isinstance(manual, UnavailableCollector)
        assert isinstance(manual, MailCollector)
        assert manual.name == "manual"
        available, cause = manual.available()
        assert available is False
        assert cause == MANUAL_CAUSE
        assert "Save as" in cause


def test_default_collectors_uses_this_host_when_no_label_is_given():
    (manual,) = default_collectors()
    assert isinstance(manual, UnavailableCollector)
    assert current_platform() == sys.platform


def test_the_package_reexports_the_public_seam():
    assert MailCollector is not None
    assert OutlookFeeder.__name__ == "OutlookFeeder"
    assert UnavailableCollector is not None
    assert callable(default_collectors)
    assert callable(render_eml)
    assert callable(write_mail)
    assert callable(write_status)


def test_the_core_files_import_without_a_platform_reader_module():
    """No feeder module needs winreg, win32com, AppKit or the OS platform."""
    for name in CORE_FILES:
        roots = imported_roots(FEEDER_SRC / name)
        assert not roots & PLATFORM_READERS, name
        assert "platform" not in roots, name  # our own .platform import is relative
