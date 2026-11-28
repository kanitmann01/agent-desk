"""Verdict and failure types shared by the validator library and CLI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    """One validation failure: a stable code plus a deterministic message."""

    code: str
    message: str


@dataclass(frozen=True)
class Verdict:
    """Outcome of validating one plugin: sorted failures, pass when empty."""

    failures: tuple[Failure, ...] = ()

    @property
    def ok(self) -> bool:
        """True when validation found nothing to report, i.e. `failures` is empty."""
        return not self.failures

    def as_dict(self) -> dict:
        """JSON-safe dict for ``--json`` output: keys ``ok`` and ``failures``."""
        return {
            "ok": self.ok,
            "failures": [
                {"code": failure.code, "message": failure.message}
                for failure in self.failures
            ],
        }
