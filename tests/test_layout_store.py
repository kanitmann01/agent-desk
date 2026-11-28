"""Layout store tests: the dashboard arrangement in SQLite, round-tripped.

The store keeps one row per card key (the four builtins plus plugin ids):
position, hidden, an optional custom title. It follows the settings and
memory store patterns: ensure_schema on construct, `with conn` writes, an
injectable nothing (no timestamps here, so no clock). Resolution is the
one place order is decided: stored rows first in their saved order, then
any card the store has never seen in canonical order (builtins, then the
caller's plugin order). Rows for plugins no longer installed are kept but
never listed, so an uninstall/reinstall cycle restores the arrangement.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.layout import (
    BUILTIN_KEYS,
    LayoutError,
    LayoutStore,
    parse_layout,
)


def _store() -> LayoutStore:
    return LayoutStore(sqlite3.connect(":memory:", check_same_thread=False))


def test_a_fresh_store_resolves_the_canonical_default_layout():
    store = _store()
    cards = store.resolve(plugin_keys=[])
    assert [c["key"] for c in cards] == list(BUILTIN_KEYS)
    assert all(c["hidden"] is False for c in cards)
    assert all(c["title"] is None for c in cards)


def test_installed_plugins_append_after_the_builtins_in_caller_order():
    store = _store()
    cards = store.resolve(plugin_keys=["b-plugin", "a-plugin"])
    assert [c["key"] for c in cards] == [
        "sales", "commitments", "research", "skills", "b-plugin", "a-plugin",
    ]


def test_replace_round_trips_order_hidden_and_title():
    store = _store()
    store.replace([
        {"key": "research", "hidden": True, "title": "Digging"},
        {"key": "sales", "hidden": False, "title": None},
        {"key": "commitments", "hidden": False, "title": "The one thing"},
    ])
    cards = store.resolve(plugin_keys=[])
    # Stored order first; the never-mentioned skills card keeps its
    # canonical place after everything the user arranged.
    assert [c["key"] for c in cards] == [
        "research", "sales", "commitments", "skills",
    ]
    by_key = {c["key"]: c for c in cards}
    assert by_key["research"]["hidden"] is True
    assert by_key["research"]["title"] == "Digging"
    assert by_key["sales"]["hidden"] is False
    assert by_key["sales"]["title"] is None
    assert by_key["commitments"]["title"] == "The one thing"


def test_the_layout_survives_a_close_and_reopen(tmp_path):
    path = tmp_path / "layout.sqlite3"
    first = LayoutStore(sqlite3.connect(str(path), check_same_thread=False))
    first.replace([
        {"key": "sales", "hidden": True, "title": "Revenue"},
    ])
    first.conn.close()
    second = LayoutStore(sqlite3.connect(str(path), check_same_thread=False))
    cards = second.resolve(plugin_keys=[])
    by_key = {c["key"]: c for c in cards}
    assert by_key["sales"]["hidden"] is True
    assert by_key["sales"]["title"] == "Revenue"


def test_replace_is_the_full_desired_layout_unmentioned_rows_are_dropped():
    store = _store()
    store.replace([
        {"key": "sales", "hidden": True, "title": "Revenue"},
        {"key": "research", "hidden": False, "title": None},
    ])
    # The next full save says nothing about sales: its row is gone and
    # the card returns to the default visible state at the canonical
    # tail. This is also how a stale plugin row is pruned: the client
    # posts what GET listed, and GET never lists uninstalled plugins.
    store.replace([
        {"key": "research", "hidden": False, "title": None},
    ])
    cards = store.resolve(plugin_keys=[])
    by_key = {c["key"]: c for c in cards}
    assert by_key["sales"]["hidden"] is False
    assert by_key["sales"]["title"] is None
    assert set(store.rows()) == {"research"}


def test_rows_for_uninstalled_plugins_are_kept_but_never_listed():
    store = _store()
    store.replace([
        {"key": "sales", "hidden": False, "title": None},
        {"key": "sales-delta-widget", "hidden": True, "title": "Delta"},
        {"key": "research", "hidden": False, "title": None},
    ])
    # Uninstalled: not listed...
    listed = [c["key"] for c in store.resolve(plugin_keys=[])]
    assert "sales-delta-widget" not in listed
    # ...but the row survives, so reinstalling restores the arrangement.
    assert "sales-delta-widget" in store.rows()
    back = store.resolve(plugin_keys=["sales-delta-widget"])
    by_key = {c["key"]: c for c in back}
    assert by_key["sales-delta-widget"]["hidden"] is True
    assert by_key["sales-delta-widget"]["title"] == "Delta"


# -- parse_layout: the POST body against the known card universe --------


def _known():
    return set(BUILTIN_KEYS) | {"sales-delta-widget"}


def test_parse_layout_accepts_the_full_desired_layout():
    parsed = parse_layout(
        [
            {"key": "sales", "hidden": True, "title": "Revenue"},
            {"key": "sales-delta-widget", "hidden": False, "title": None},
        ],
        _known(),
    )
    assert parsed == [
        {"key": "sales", "hidden": True, "title": "Revenue"},
        {"key": "sales-delta-widget", "hidden": False, "title": None},
    ]


def test_parse_layout_fills_the_optional_fields():
    parsed = parse_layout([{"key": "sales"}], _known())
    assert parsed == [{"key": "sales", "hidden": False, "title": None}]


def test_parse_layout_strips_titles_and_blank_means_none():
    parsed = parse_layout(
        [{"key": "sales", "title": "  Revenue  "}, {"key": "research", "title": "   "}],
        _known(),
    )
    assert parsed[0]["title"] == "Revenue"
    assert parsed[1]["title"] is None


def test_parse_layout_rejects_an_unknown_card_with_the_named_error():
    with pytest.raises(LayoutError) as exc:
        parse_layout([{"key": "salez"}], _known())
    assert exc.value.code == "layout:unknown-card"
    assert exc.value.key == "salez"


def test_parse_layout_rejects_a_plugin_id_that_is_not_installed():
    # Not installed means not known: a stale or invented plugin id is the
    # same named refusal as a typo'd builtin.
    with pytest.raises(LayoutError) as exc:
        parse_layout([{"key": "uninstalled-plugin"}], _known())
    assert exc.value.code == "layout:unknown-card"


def test_parse_layout_rejects_duplicates():
    with pytest.raises(LayoutError) as exc:
        parse_layout(
            [{"key": "sales"}, {"key": "sales"}],
            _known(),
        )
    assert exc.value.code == "layout:duplicate-card"


@pytest.mark.parametrize("bad", [
    "sales",                       # not a list
    [1, 2],                        # entries must be objects
    [{"key": 7}],                  # the key must be a string
    [{"key": "  "}],               # blank key
    [{}],                          # missing key
    [{"key": "sales", "hidden": "yes"}],  # hidden must be a bool
    [{"key": "sales", "title": 4}],        # title is a string or null
    [{"key": "sales", "title": "x" * 121}],  # titles are capped
])
def test_parse_layout_rejects_malformed_entries(bad):
    with pytest.raises(LayoutError) as exc:
        parse_layout(bad, _known())
    assert exc.value.code == "layout:invalid-card"


def test_parse_layout_accepts_a_title_at_the_cap():
    parsed = parse_layout([{"key": "sales", "title": "x" * 120}], _known())
    assert parsed[0]["title"] == "x" * 120
