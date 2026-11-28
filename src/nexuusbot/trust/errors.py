"""Trust verification failures.

Every failure is fail-closed and carries a stable machine code.
"""
from __future__ import annotations


class TrustError(Exception):
    """A trust verification failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the code and message, and render them as one line.

        code is the stable vocabulary callers switch on - trust:revoked,
        trust:no-anchor, trust:stale-epoch - while message is prose for logs.
        super() receives them already joined, so a printed traceback keeps the
        code instead of showing only the explanation.
        """
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")
