"""Shared fakes for the probe tests.

Kept outside test collection (module name does not start with test_) so
individual test files can import canned runner/reacher results without
duplicating them. No fake here touches the network, OneDrive or EDR.
"""

import shutil
from pathlib import Path

from agentdesk.probe.core import GateResult, RunResult


class FakeRunner:
    """Records commands and returns a canned RunResult."""

    def __init__(self, returncode=0, stdout="", stderr="", error=""):
        self._result = RunResult(returncode=returncode, stdout=stdout, stderr=stderr, error=error)
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        return self._result


class ExplodingRunner:
    """Simulates a command that cannot even start (e.g. blocked)."""

    def __init__(self, message="Access is denied."):
        self.message = message
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        raise OSError(self.message)


class FakeUvFinder:
    def __init__(self, path):
        self.path = path
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.path


class FakeReacher:
    """Returns a canned HTTP status or connection error for a URL."""

    def __init__(self, status=None, error=None):
        self.status = status
        self.error = error
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        from agentdesk.probe.core import ReachResult

        return ReachResult(status=self.status, error=self.error, url=url)


class FakeOneDriveDiscoverer:
    def __init__(self, path=None, how=""):
        self.path = path
        self.how = how

    def __call__(self):
        from agentdesk.probe.core import OneDriveInfo

        if self.path is None:
            return None
        return OneDriveInfo(path=self.path, how=self.how or "fake discovery")


class FakeProcessLister:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self._result = RunResult(returncode=returncode, stdout=stdout, stderr=stderr)

    def __call__(self):
        return self._result


def gate(key, number, status, evidence=("fake evidence",), note="", title=None):
    """Build a GateResult quickly for aggregator/report tests (title defaults to the key)."""
    return GateResult(key=key, number=number, title=title or key, status=status, evidence=tuple(evidence), note=note)


class SequenceRunner:
    """Returns canned RunResults one per command, in order.

    Models multi-step flows (uv venv succeeds, then the install fails).
    Reuses the last result if more commands arrive than results given.
    """

    def __init__(self, *results):
        self.results = list(results)
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(list(cmd))
        index = min(len(self.commands) - 1, len(self.results) - 1)
        return self.results[index]


class RecordingWriter:
    """The injectable write_text adapter: records calls, then performs them.

    Recording proves the gate wrote through the injected callable; the
    delegation keeps tests that read the written file working (tmp-path
    scoped, so nothing outside the test's own directory is touched).
    """

    def __init__(self):
        self.calls = []

    def __call__(self, path, text, encoding="utf-8"):
        self.calls.append((Path(path), text, encoding))
        Path(path).write_text(text, encoding=encoding)


class RecordingCopier:
    """The injectable copy_file adapter: records calls, then performs them."""

    def __init__(self):
        self.calls = []

    def __call__(self, source, dest):
        self.calls.append((Path(source), Path(dest)))
        shutil.copy(source, dest)
