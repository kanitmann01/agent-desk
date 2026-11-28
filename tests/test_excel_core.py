"""Delta arithmetic: the pure core of the 24-hour diff.

Row hashes are the currency: the snapshot store keeps digests, the delta
compares multisets of digests, and a row edited in place shows up as one
removed plus one added.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nexuusbot.excel.core import Delta, compute_delta, row_hash


def test_row_hash_is_stable_across_calls_and_order_sensitive():
    assert row_hash(["a", 1.0]) == row_hash(["a", 1.0])
    assert row_hash(["a", 1.0]) != row_hash([1.0, "a"])


def test_identical_tables_yield_an_empty_delta():
    rows = [["A", 1.0], ["B", 2.0]]
    delta = compute_delta(rows, rows)
    assert delta.added == [] and delta.removed == []
    assert delta.unchanged == 2
    assert delta.is_empty


def test_edited_row_is_removed_plus_added():
    old = [["Atlas", 41.0], ["Field", 12.0]]
    new = [["Atlas", 44.0], ["Field", 12.0]]
    delta = compute_delta(old, new)
    assert delta.added == [["Atlas", 44.0]]
    assert delta.removed == [["Atlas", 41.0]]
    assert delta.unchanged == 1


def test_added_and_removed_rows_keep_table_order():
    old = [["keep1"], ["drop1"], ["keep2"], ["drop2"]]
    new = [["keep1"], ["new1"], ["keep2"], ["new2"]]
    delta = compute_delta(old, new)
    assert delta.added == [["new1"], ["new2"]]
    assert delta.removed == [["drop1"], ["drop2"]]


def test_duplicated_row_counts_with_multiplicity():
    old = [["A"]]
    new = [["A"], ["A"]]
    delta = compute_delta(old, new)
    assert delta.added == [["A"]]
    assert delta.unchanged == 1


def test_empty_tables_produce_empty_deltas():
    delta = compute_delta([], [])
    assert delta.is_empty and delta.unchanged == 0
    full = compute_delta([], [["only"]])
    assert full.added == [["only"]] and full.unchanged == 0


def test_delta_serializes_to_the_api_shape():
    payload = Delta(added=[["x"]], removed=[["y"]], unchanged=3).to_json()
    assert payload == {"added": [["x"]], "removed": [["y"]], "unchanged": 3}
