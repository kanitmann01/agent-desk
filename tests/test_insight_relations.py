"""Tests for the workbook table maths.

Each detector is proved twice: once with a table that clears the spec's
threshold, and once with a table that misses it by a little, because the
refusals are the part of this module that keeps the card honest.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from agentdesk.insight import relations


def _table(headers, rows):
    table = relations.read_table({"headers": headers, "rows": rows})
    assert table is not None
    return table


def _correlation_table(values):
    return _table(["x", "y"], [[index + 1, value] for index, value in enumerate(values)])


# -- messy cells -----------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("1,234.50", 1234.5),
        ("$1,234.50", 1234.5),
        ("£ 900", 900.0),
        ("(1,200)", -1200.0),
        ("12%", 12.0),
        ("−5", -5.0),
        ("+3.5", 3.5),
        ("  42  ", 42.0),
        ("0", 0.0),
        (7, 7.0),
        (7.5, 7.5),
    ],
)
def test_parse_number_reads_ordinary_cell_shapes(cell, expected):
    assert relations.parse_number(cell) == expected


@pytest.mark.parametrize(
    "cell",
    ["", "   ", "-", "n/a", "N/A", "(blank)", "None", "12abc", "1 234", "1.234,56", "$", "%"],
)
def test_parse_number_refuses_what_it_cannot_read(cell):
    assert relations.parse_number(cell) is None


@pytest.mark.parametrize("cell", [None, True, False, float("nan"), float("inf"), ["1"], {"n": 1}])
def test_parse_number_refuses_non_numeric_types(cell):
    assert relations.parse_number(cell) is None


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("2026-01-31", date(2026, 1, 31)),
        ("2026-01-31 09:30", date(2026, 1, 31)),
        ("31/01/2026", date(2026, 1, 31)),
        ("01/31/2026", date(2026, 1, 31)),
        ("01/02/2026", date(2026, 2, 1)),
        ("31 Jan 2026", date(2026, 1, 31)),
        ("Jan 31, 2026", date(2026, 1, 31)),
        ("31 January 2026", date(2026, 1, 31)),
    ],
)
def test_parse_date_reads_text_dates(cell, expected):
    assert relations.parse_date(cell) == expected


@pytest.mark.parametrize(
    "cell", ["2026-02-30", "2026-13-01", "n/a", "", "45678", "Q1 2026", "31/13/2026"]
)
def test_parse_date_refuses_what_it_cannot_read(cell):
    assert relations.parse_date(cell) is None


def test_excel_serial_numbers_are_not_dates():
    # A workbook date arrives as a bare number; reading 45678 as a day would
    # let an amount invent a trend.
    assert relations.parse_date(45678) is None
    assert relations.parse_date(45678.0) is None


# -- reading the table -----------------------------------------------------


@pytest.mark.parametrize(
    "value", [None, "table", [], {}, {"headers": ["a"]}, {"headers": ["a", "b"]}]
)
def test_read_table_refuses_anything_without_two_columns_and_a_row(value):
    assert relations.read_table(value) is None


def test_read_table_pads_blank_rows_and_stringifies_cells():
    table = _table(["name", "amount"], [["a", 3], ["b", None], ["", ""], ["c", " 4 "]])
    assert table.rows == (("a", "3"), ("b", ""), ("c", " 4 "))
    assert table.headers == ("name", "amount")


def test_read_table_is_bounded_to_the_tracker_limits():
    headers = [f"c{index}" for index in range(12)]
    rows = [[str(index)] * 12 for index in range(80)]
    table = _table(headers, rows)
    assert len(table.headers) == 10
    assert len(table.rows) == 60


def test_columns_are_classified_and_percent_is_remembered():
    table = _table(
        ["when", "amount", "share", "note"],
        [
            ["2026-01-01", "1,200", "40%", "alpha"],
            ["2026-02-01", "900", "30%", "beta"],
            ["2026-03-01", "700", "30%", "gamma"],
        ],
    )
    kinds = [column.kind for column in table.columns]
    assert kinds == ["date", "number", "number", "text"]
    assert table.columns[2].percent is True
    assert table.columns[1].percent is False


def test_a_half_numeric_column_stays_text():
    table = _table(
        ["mixed", "other"],
        [["1", "a"], ["2", "b"], ["", "c"], ["n/a", "d"], ["x", "e"], ["y", "f"]],
    )
    assert table.columns[0].kind == "text"


# -- correlation -----------------------------------------------------------


def test_correlation_fires_on_a_clear_pair():
    found = relations.correlations(_correlation_table([3, 6, 9, 12, 15, 18, 21, 24]))
    assert len(found) == 1
    finding = found[0]
    assert finding.rows == 8
    assert "r = 1.00" in finding.text
    assert "very strong" in finding.text
    assert "rises with" in finding.text
    assert finding.chart == "table"


def test_correlation_accepts_the_strong_side_of_the_boundary():
    found = relations.correlations(_correlation_table([7, 8, 16, 12, 12, 12, 13, 14]))
    assert len(found) == 1
    assert abs(found[0].score - 0.609957) < 0.001
    assert "moderate" in found[0].text


def test_correlation_refuses_just_below_the_boundary():
    found = relations.correlations(_correlation_table([7, 8, 16, 18, 18, 12, 20, 14]))
    assert found == []


def test_correlation_refuses_seven_paired_points():
    found = relations.correlations(_correlation_table([3, 6, 9, 12, 15, 18, 21]))
    assert found == []


def test_correlation_ignores_rows_where_either_cell_is_missing():
    rows = [[index + 1, 3 * (index + 1)] for index in range(8)]
    rows += [["9", "n/a"], ["n/a", "10"]]
    found = relations.correlations(_table(["x", "y"], rows))
    assert len(found) == 1
    assert found[0].rows == 8


def test_correlation_refuses_a_constant_column():
    found = relations.correlations(_correlation_table([5, 5, 5, 5, 5, 5, 5, 5]))
    assert found == []


def test_correlation_refuses_two_identical_columns():
    table = _table(["x", "y"], [[index, index] for index in range(1, 9)])
    # Perfectly parallel columns are one series entered twice, not a link.
    assert relations.correlations(table) == []


# -- trend -----------------------------------------------------------------


def _trend_table(values, dates=None):
    dates = dates or [f"2026-0{index + 1}-01" for index in range(len(values))]
    return _table(["when", "amount"], [[day, value] for day, value in zip(dates, values)])


def test_trend_fires_on_a_rising_column():
    found = relations.trends(_trend_table([10, 11, 12, 13, 14, 15]))
    assert len(found) == 1
    finding = found[0]
    assert finding.chart == "line"
    assert finding.columns == ("amount", "when")
    assert finding.rows == 6
    assert "rose from 10 to 15" in finding.text
    assert "5 of 5 steps" in finding.text


def test_trend_reads_a_falling_column():
    found = relations.trends(_trend_table([15, 14, 13, 12, 11, 10]))
    assert len(found) == 1
    assert "fell from 15 to 10" in found[0].text


def test_trend_refuses_five_dated_points():
    assert relations.trends(_trend_table([10, 11, 12, 13, 14])) == []


def test_trend_refuses_a_jagged_column():
    # Three of five steps move one way: 0.6, below the 0.7 floor.
    assert relations.trends(_trend_table([1, 2, 1, 2, 1, 3])) == []


def test_trend_refuses_a_flat_column():
    assert relations.trends(_trend_table([10, 10, 10, 10, 10, 10])) == []


def test_trend_needs_a_dated_column():
    table = _table(["when", "amount"], [[str(index), index] for index in range(1, 8)])
    assert relations.trends(table) == []


# -- share -----------------------------------------------------------------


def test_share_fires_on_a_dominant_group():
    found = relations.shares(_table(["region", "amount"], [["A", 51], ["B", 30], ["C", 19]]))
    assert len(found) == 1
    finding = found[0]
    assert finding.chart == "bar"
    assert finding.rows == 3
    assert "A is 51%" in finding.text
    assert "3 groups" in finding.text
    assert finding.suggested == (0,)


def test_share_refuses_two_groups():
    assert relations.shares(_table(["region", "amount"], [["A", 70], ["B", 30]])) == []


def test_share_refuses_a_leading_group_under_half():
    found = relations.shares(_table(["region", "amount"], [["A", 49], ["B", 49], ["C", 2]]))
    assert found == []


def test_share_refuses_percentage_columns():
    table = _table(["region", "margin"], [["A", "40%"], ["B", "30%"], ["C", "30%"]])
    assert table.columns[1].percent is True
    assert relations.shares(table) == []


def test_share_refuses_negative_values():
    assert relations.shares(_table(["region", "amount"], [["A", -1], ["B", 5], ["C", 2]])) == []


# -- ratio -----------------------------------------------------------------


def _ratio_table(rows):
    return _table(["region", "amount"], rows)


def test_ratio_fires_on_a_near_tie():
    found = relations.ratios(
        _ratio_table([["A", 30], ["A", 30], ["B", 50], ["C", 1], ["C", 1]])
    )
    assert len(found) == 1
    finding = found[0]
    assert finding.rows == 5
    assert "within 1.2x" in finding.text
    assert finding.suggested == (0, 1, 2)


def test_ratio_refuses_a_clear_leader():
    found = relations.ratios(
        _ratio_table([["A", 40], ["A", 40], ["B", 50], ["C", 1], ["C", 1]])
    )
    assert found == []


def test_ratio_refuses_four_rows():
    found = relations.ratios(_ratio_table([["A", 30], ["B", 50], ["C", 1], ["C", 1]]))
    assert found == []


def test_ratio_refuses_when_every_label_is_unique():
    rows = [[label, value] for label, value in zip("abcdef", [10, 11, 12, 13, 14, 15])]
    assert relations.ratios(_ratio_table(rows)) == []


# -- outliers --------------------------------------------------------------


def _outlier_table(values, labels=None):
    labels = labels or [f"row {index + 1}" for index in range(len(values))]
    return _table(["name", "amount"], [[name, value] for name, value in zip(labels, values)])


def test_outlier_fires_on_the_row_far_from_the_rest():
    labels = ["Dana", "Sam", "Alex", "Jo", "Kim", "Lee", "Max", "Nia"]
    found = relations.outliers(_outlier_table([10] * 7 + [13], labels))
    assert len(found) == 1
    finding = found[0]
    assert finding.rows == 8
    assert finding.suggested == (7,)
    assert "Nia" in finding.text
    assert "2.6 standard deviations above" in finding.text
    assert abs(finding.score - 2.6458) < 0.001


def test_outlier_refuses_seven_points():
    assert relations.outliers(_outlier_table([10] * 6 + [13])) == []


def test_outlier_refuses_a_mild_gap():
    assert relations.outliers(_outlier_table([10] * 6 + [12, 13])) == []


def test_outlier_refuses_a_flat_column():
    assert relations.outliers(_outlier_table([10] * 8)) == []


def test_outlier_names_the_row_from_the_label_column():
    table = _table(
        ["code", "name", "amount"],
        [
            ["X-1", "Dana", 10],
            ["X-2", "Sam", 10],
            ["X-3", "Alex", 10],
            ["X-4", "Jo", 10],
            ["X-5", "Kim", 10],
            ["X-6", "Lee", 10],
            ["X-7", "Max", 10],
            ["X-8", "Nia", 13],
        ],
    )
    found = relations.outliers(table, label_column="name")
    assert len(found) == 1
    assert "Nia" in found[0].text


# -- provenance: cells, rule, and the outlier's cause and action -----------


@pytest.mark.parametrize(
    ("key", "threshold"),
    [
        ("trend", "70%"),
        ("correlation", "0.6"),
        ("share", "50%"),
        ("ratio", "1.5x"),
        ("outlier", "2.5"),
    ],
)
def test_every_detector_names_its_columns_rule_and_cells(key, threshold):
    finding = _finding(key)
    assert finding.columns
    assert threshold in finding.rule
    assert finding.cells
    assert all(cell.strip() for cell in finding.cells)


def test_trend_cells_cite_both_ends_of_the_range():
    finding = _finding("trend")
    assert finding.cells == ("B2: 10", "A2: 2026-01-01", "B7: 15", "A7: 2026-06-01")


def test_correlation_cells_cite_the_first_and_last_pairs():
    finding = _finding("correlation")
    assert finding.cells == ("A2: 1", "B2: 3", "A9: 8", "B9: 24")


def test_share_cells_cite_the_top_group():
    finding = _finding("share")
    assert finding.cells == ("A2: A", "B2: 51")


def test_ratio_cells_cite_both_sides():
    finding = _finding("ratio")
    assert finding.cells == ("A2: A", "B2: 30", "A4: B", "B4: 50")


def test_outlier_names_the_segment_that_shifted_most():
    rows = [
        ["North", 10], ["North", 10], ["North", 10], ["North", 10],
        ["South", 10], ["South", 10], ["South", 10], ["South", 30],
    ]
    found = relations.outliers(_table(["region", "amount"], rows))
    assert len(found) == 1
    finding = found[0]
    assert finding.suggested == (7,)
    assert finding.segment == "South"
    assert "South rows average 15 against 10 elsewhere" in finding.text
    assert "Check the South rows' amount entries first." in finding.text
    assert finding.action == "Check the South rows' amount entries first."
    assert finding.cells == ("B9: 30", "A9: South")


def test_an_exact_date_column_names_the_shifted_date_segment():
    rows = [
        ["2026-01-05", 10], ["2026-01-05", 10], ["2026-01-05", 10], ["2026-01-05", 10],
        ["2026-02-05", 10], ["2026-02-05", 10], ["2026-02-05", 10], ["2026-02-05", 30],
    ]
    found = relations.outliers(_table(["when", "amount"], rows))
    assert len(found) == 1
    finding = found[0]
    assert finding.suggested == (7,)
    assert finding.segment == "2026-02-05"
    assert "2026-02-05 rows average 15 against 10 elsewhere" in finding.text
    assert finding.cells == ("B9: 30", "A9: 2026-02-05")


def test_a_date_column_falls_back_to_month_buckets():
    rows = [
        ["2026-01-05", 10], ["2026-01-06", 10], ["2026-01-07", 10], ["2026-01-08", 10],
        ["2026-02-05", 10], ["2026-02-06", 10], ["2026-02-07", 10], ["2026-02-08", 31],
    ]
    found = relations.outliers(_table(["when", "amount"], rows))
    assert len(found) == 1
    finding = found[0]
    assert finding.segment == "2026-02"
    assert "2026-02 rows average 15.25 against 10 elsewhere" in finding.text


def test_a_unique_date_per_row_is_never_a_segment():
    rows = [[f"2026-{month + 1:02d}-01", 10] for month in range(7)]
    rows.append(["2026-08-01", 24])
    found = relations.outliers(_table(["when", "amount"], rows))
    assert len(found) == 1
    finding = found[0]
    assert finding.suggested == (7,)
    assert finding.segment == ""
    assert "No column here splits the rows into groups." in finding.text
    assert finding.action == "Check row 8's amount entry first."
    assert finding.cells == ("B9: 24",)


def test_a_flat_label_table_gets_a_row_check_without_a_segment():
    labels = ["Dana", "Sam", "Alex", "Jo", "Kim", "Lee", "Max", "Nia"]
    found = relations.outliers(_outlier_table([10] * 7 + [24], labels))
    assert len(found) == 1
    finding = found[0]
    assert finding.suggested == (7,)
    assert finding.segment == ""
    assert "No column here splits the rows into groups." in finding.text
    assert finding.action == "Check row 8's amount entry first."
    assert "Nia" in finding.text


# -- ordering and chart choice --------------------------------------------


def _mixed_table():
    rows = []
    regions = ["A"] * 7 + ["B"] * 3 + ["C"] * 2
    booked = [10] * 7 + [5] * 3 + [3] * 2
    for index in range(12):
        rows.append([f"2026-{index + 1:02d}-01", 10 + index, regions[index], booked[index]])
    return _table(["when", "amount", "region", "booked"], rows)


def test_findings_are_ordered_by_strength():
    found = relations.findings(_mixed_table())
    assert found[0].key == "trend"
    assert "share" in [finding.key for finding in found]


def test_findings_break_ties_by_the_larger_measure():
    rows = [
        [index + 1, 3 * (index + 1), value]
        for index, value in enumerate([7, 8, 16, 12, 12, 12, 13, 14])
    ]
    found = relations.findings(_table(["x", "triple", "weak"], rows))
    assert [finding.key for finding in found] == ["correlation"] * 3
    assert found[0].columns == ("x", "triple")
    assert found[0].score == pytest.approx(1.0)


def test_findings_keeps_a_share_and_drops_the_same_pair_as_a_near_tie():
    rows = [["A", 50], ["A", 50], ["B", 90], ["C", 5], ["C", 5]]
    found = relations.findings(_table(["region", "amount"], rows))
    keys = [finding.key for finding in found]
    assert "share" in keys
    assert "ratio" not in keys


def test_an_all_text_table_supports_nothing():
    table = _table(["name", "note"], [["Dana", "paid"], ["Sam", "late"], ["Jo", "paid"]])
    assert relations.findings(table) == []


def _finding(key):
    table = {
        "trend": lambda: relations.trends(_trend_table([10, 11, 12, 13, 14, 15]))[0],
        "correlation": lambda: relations.correlations(
            _correlation_table([3, 6, 9, 12, 15, 18, 21, 24])
        )[0],
        "share": lambda: relations.shares(
            _table(["region", "amount"], [["A", 51], ["B", 30], ["C", 19]])
        )[0],
        "ratio": lambda: relations.ratios(
            _ratio_table([["A", 30], ["A", 30], ["B", 50], ["C", 1], ["C", 1]])
        )[0],
        "outlier": lambda: relations.outliers(_outlier_table([10] * 7 + [13]))[0],
    }[key]()
    return table


@pytest.mark.parametrize(
    ("key", "shape"),
    [
        ("trend", "line"),
        ("correlation", "table"),
        ("share", "bar"),
        ("ratio", "table"),
        ("outlier", "bar"),
    ],
)
def test_auto_chart_choice_follows_the_relationship(key, shape):
    chosen, sentence = relations.chart_choice(_finding(key), "auto")
    assert chosen == shape
    assert sentence.endswith(".")


def test_auto_chart_sentence_names_the_shape_and_the_reason():
    chosen, sentence = relations.chart_choice(_finding("trend"), "auto")
    assert chosen == "line"
    assert sentence.startswith("A line chart fits this:")
    assert "move in a known order" in sentence


def test_stated_preference_wins_and_is_explained():
    chosen, sentence = relations.chart_choice(_finding("trend"), "table")
    assert chosen == "table"
    assert "Your chart setting asks for a table" in sentence
    assert "left alone this reading would draw a line chart" in sentence


def test_stated_preference_that_agrees_is_not_scolded():
    chosen, sentence = relations.chart_choice(_finding("share"), "bar")
    assert chosen == "bar"
    assert "and it fits" in sentence


def test_an_unknown_preference_falls_back_to_auto():
    chosen, sentence = relations.chart_choice(_finding("share"), "pie")
    assert chosen == "bar"
    assert "chart setting" not in sentence
