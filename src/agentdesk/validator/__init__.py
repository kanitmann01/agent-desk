"""Agent Desk plugin validator: manifest in, verdict out.

The same code runs as a standalone CLI (``python -m agentdesk.validator``),
in the app's install path, and in registry CI.
"""

from .cli import main
from .core import validate_plugin
from .model import Failure, Verdict
from .reader import ValidatorIOError

__all__ = ["Failure", "Verdict", "ValidatorIOError", "validate_plugin", "main"]
