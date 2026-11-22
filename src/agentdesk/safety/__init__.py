"""Safety checks the desk applies to text it is about to trust.

The threat patterns are shared by ranking, profile review and skill
refinement, so they live in one place instead of drifting apart.
"""

from .threat_patterns import first_threat_message, scan_for_threats

__all__ = ["first_threat_message", "scan_for_threats"]
