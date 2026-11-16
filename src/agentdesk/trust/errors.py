"""Trust verification failures.

Every failure is fail-closed and carries a stable machine code.
"""
from __future__ import annotations


class TrustError(Exception):
    """A trust verification failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
