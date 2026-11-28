"""Wizard: English in, a validated Class D plugin draft out (ticket #11).

The manager describes what she wants; the wizard asks the choices that
description leaves open (each with a default, never typed technical input),
drafts a declarative plugin from those choices, and pushes it through the same
validator as every other plugin, repairing at most three times before
escalating honestly with a feature_request payload instead of shipping a
guess. When an AI connection is saved the description fills the choices in
first, from the closed vocabulary in ``nexuusbot.wizard.vocabulary``.
"""

from nexuusbot.wizard.core import (
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
    Choice,
    WizardCompiler,
    WizardError,
    WizardSession,
    WizardStore,
    merge_answers,
    normalize_answers,
    questions_for_answers,
    resolve_choice,
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
    "Choice",
    "WizardCompiler",
    "WizardError",
    "WizardSession",
    "WizardStore",
    "merge_answers",
    "normalize_answers",
    "questions_for_answers",
    "resolve_choice",
    "safe_slug",
]
