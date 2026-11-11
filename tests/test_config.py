"""Config file tests: the parser and the apply step, in isolation.

The config file is the only non-env way to configure the app, so its
contract is pinned here line by line: comments, quotes, whitespace,
prefix filtering and the env-wins precedence. The loader is pointed at
plain dicts, never os.environ, so nothing here can leak a variable into
the rest of the suite.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.config import load_env_file, parse_env_file


def test_parses_simple_key_value_lines():
    assert parse_env_file("AGENTDESK_LLM_BASE=https://llm.corp/v1\n") == {
        "AGENTDESK_LLM_BASE": "https://llm.corp/v1"
    }


def test_comments_and_blank_lines_are_ignored():
    text = (
        "# the company endpoint\n"
        "\n"
        "   \n"
        "#AGENTDESK_LLM_BASE=https://commented.example\n"
        "AGENTDESK_LLM_KEY=secret\n"
    )
    assert parse_env_file(text) == {"AGENTDESK_LLM_KEY": "secret"}


def test_quotes_are_stripped():
    text = 'AGENTDESK_LLM_BASE="https://llm.corp"\nAGENTDESK_LLM_KEY=\'abc 123\'\n'
    assert parse_env_file(text) == {
        "AGENTDESK_LLM_BASE": "https://llm.corp",
        "AGENTDESK_LLM_KEY": "abc 123",
    }


def test_surrounding_whitespace_is_trimmed():
    text = "  AGENTDESK_LLM_MODEL = gpt-4o-mini  \n"
    assert parse_env_file(text) == {"AGENTDESK_LLM_MODEL": "gpt-4o-mini"}


def test_value_may_contain_equals_signs():
    text = "AGENTDESK_LLM_BASE=https://llm.corp/v1?trace=1\n"
    assert parse_env_file(text) == {"AGENTDESK_LLM_BASE": "https://llm.corp/v1?trace=1"}


def test_non_prefixed_keys_are_not_honored():
    text = "PATH=/usr/bin\nHOME=/home\nOTHER_VALUE=x\n"
    assert parse_env_file(text) == {}


def test_empty_values_are_dropped():
    assert parse_env_file("AGENTDESK_LLM_KEY=\n") == {}


def test_lines_without_equals_are_ignored():
    assert parse_env_file("just some prose\nAGENTDESK_LLM_KEY=k\n") == {
        "AGENTDESK_LLM_KEY": "k"
    }


def test_load_applies_prefixed_keys_to_the_given_environment(tmp_path):
    # A plain dict, never os.environ: the loader writes its mapping
    # directly, and a leaked key would flip later tests' expectations.
    file = tmp_path / "config.env"
    file.write_text("AGENTDESK_LLM_BASE=https://llm.corp\n", encoding="utf-8")
    environ: dict[str, str] = {}
    applied = load_env_file(file, environ=environ)
    assert applied == {"AGENTDESK_LLM_BASE": "https://llm.corp"}
    assert environ["AGENTDESK_LLM_BASE"] == "https://llm.corp"


def test_load_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "absent.env") == {}


def test_load_existing_environment_wins(tmp_path):
    file = tmp_path / "config.env"
    file.write_text(
        "AGENTDESK_LLM_BASE=https://from-file.example\n"
        "AGENTDESK_LLM_KEY=file-key\n"
        "AGENTDESK_LLM_MODEL=file-model\n",
        encoding="utf-8",
    )
    environ = {
        "AGENTDESK_LLM_BASE": "https://from-env.example",
        "AGENTDESK_LLM_KEY": "env-key",
    }
    applied = load_env_file(file, environ=environ)
    assert applied == {"AGENTDESK_LLM_MODEL": "file-model"}
    assert environ["AGENTDESK_LLM_BASE"] == "https://from-env.example"
    assert environ["AGENTDESK_LLM_KEY"] == "env-key"
    assert environ["AGENTDESK_LLM_MODEL"] == "file-model"


def test_load_reports_nothing_when_every_key_already_set(tmp_path):
    file = tmp_path / "config.env"
    file.write_text("AGENTDESK_DATA=from-file\n", encoding="utf-8")
    environ = {"AGENTDESK_DATA": "already-set"}
    assert load_env_file(file, environ=environ) == {}
    assert environ["AGENTDESK_DATA"] == "already-set"
