"""Wizard: English in, a validated Class D plugin draft out (ticket #11).

The manager describes what she wants; the compiler asks at most five
multiple-choice questions (each with a default, never typed technical
input), drafts a declarative plugin, and pushes it through the same
validator as every other plugin, repairing at most three times before
escalating honestly with a feature_request payload instead of shipping
a guess.
"""

from agentdesk.wizard.core import (
    DEFAULT_QUESTIONS,
    MAX_QUESTIONS,
    MAX_REPAIRS,
    STATE_APPROVED,
    STATE_BUILDING,
    STATE_ESCALATED,
    STATE_PREVIEW,
    STATE_QUESTIONS,
    VOCABULARY,
    WIZARD_STATES,
    WizardCompiler,
    WizardError,
    WizardSession,
    WizardStore,
    safe_slug,
)

__all__ = [
    "DEFAULT_QUESTIONS",
    "MAX_QUESTIONS",
    "MAX_REPAIRS",
    "STATE_APPROVED",
    "STATE_BUILDING",
    "STATE_ESCALATED",
    "STATE_PREVIEW",
    "STATE_QUESTIONS",
    "VOCABULARY",
    "WIZARD_STATES",
    "WizardCompiler",
    "WizardError",
    "WizardSession",
    "WizardStore",
    "safe_slug",
]
