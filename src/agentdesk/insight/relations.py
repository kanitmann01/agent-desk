"""Pure table maths for the workbook reading.

The card already shows one total. This module is the part of the reading
that can be checked: cells become numbers and dates, columns are
classified, and five conservative detectors look for a relationship the
total hides. Every finding carries its own numbers and the count of rows it
rests on, and a detector that cannot clear the threshold in
specs/009-coupled-intelligence.md returns nothing, because a weak claim is
worse than silence.

Two refusals are deliberate. A percentage column never yields a share or a
near-tie, because a total of percentages has no meaning. And a date is read
from text only: a workbook stores a date as a serial number, and 45678 is
indistinguishable from a quantity, so treating it as a calendar would let an
amount invent a trend.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date as _Date

# The tracker sends at most this much, and a reading never works over more.
MAX_ROWS = 60
MAX_COLUMNS = 10

MIN_PAIRED = 8
MIN_CORRELATION = 0.6
MIN_TREND_POINTS = 6
MIN_MONOTONIC = 0.7
MIN_GROUPS = 3
MIN_TOP_SHARE = 0.5
MIN_OUTLIER_POINTS = 8
MIN_Z = 2.5
MIN_RATIO_ROWS = 5
MAX_RATIO = 1.5

# Strongest first: a movement in time or a coefficient describes the whole
# range, a share describes its composition, a near-tie describes two groups,
# and an outlier describes one row. Within one rank the larger measure wins,
# then the column names, so the order never depends on the order the
# detectors happened to run in.
STRENGTH = ("trend", "correlation", "share", "ratio", "outlier")

AUTO_CHART = {
    "trend": "line",
    "correlation": "table",
    "share": "bar",
    "ratio": "table",
    "outlier": "bar",
}

LABELS = {
    "trend": "Trend",
    "correlation": "Link",
    "share": "Share",
    "ratio": "Split",
    "outlier": "Outlier",
}

_CHART_REASON = {
    "line": "the values move in a known order, so the line carries the shape",
    "bar": "the comparison is between groups, so one bar per group keeps it visible",
    "table": "the numbers themselves are the point, so a table lets you check them",
}

_CHART_NOUN = {"line": "a line chart", "bar": "a bar chart", "table": "a table"}

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MISSING = frozenset(
    {"", "-", "--", "---", "n/a", "na", "n.a.", "n.a", "none", "null", "nil", "tbd", "?"}
)
_CURRENCY = "$£€¥₹"

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)")
_ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?:[T ].*)?$")
_DAY_MONTH_NAME = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3,9})[ -](\d{4})$")
_MONTH_NAME_DAY = re.compile(r"^([A-Za-z]{3,9})[ -](\d{1,2}),?[ -](\d{4})$")


# -- cells -----------------------------------------------------------------


def parse_number(cell: object) -> float | None:
    """One cell as a number, or None when it is not one.

    Thousands separators, currency symbols, a trailing percent and
    accounting parentheses are understood; anything else is refused rather
    than repaired. A percent cell reads as its percent value (12% -> 12) and
    the column remembers the unit for display.
    """
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        number = float(cell)
        return number if math.isfinite(number) else None
    if not isinstance(cell, str):
        return None
    text = cell.strip().replace("\u2212", "-")
    if text.lower() in _MISSING:
        return None
    negative = len(text) > 1 and text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    if text.endswith("%"):
        text = text[:-1].strip()
    text = text.strip(_CURRENCY + " \u00a0")
    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        # 1.234,56 is a different convention, not a thousands separator:
        # reading it as 1.23456 would be a quiet error.
        return None
    text = text.replace(",", "").replace("_", "")
    if not _NUMBER.fullmatch(text):
        return None
    number = float(text)
    if not math.isfinite(number):
        return None
    return -number if negative else number


def parse_date(cell: object) -> _Date | None:
    """One cell as a calendar date, or None.

    Only text is read: an ISO date, a numeric date (day first when both
    readings are possible, as British workbooks write them), and a date with
    a month name. A bare number is never a date.
    """
    if not isinstance(cell, str):
        return None
    text = cell.strip()
    if text.lower() in _MISSING:
        return None
    match = _ISO_DATE.match(text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        return _date(year, month, day)
    match = _NUMERIC_DATE.match(text)
    if match:
        first, second, year = (int(part) for part in match.groups())
        if first > 12 and second <= 12:
            day, month = first, second
        elif second > 12 and first <= 12:
            day, month = second, first
        else:
            day, month = first, second
        return _date(year, month, day)
    match = _DAY_MONTH_NAME.match(text)
    if match:
        day, name, year = int(match.group(1)), match.group(2), int(match.group(3))
        month = _MONTHS.get(name.lower())
        return _date(year, month, day) if month else None
    match = _MONTH_NAME_DAY.match(text)
    if match:
        name, day, year = match.group(1), int(match.group(2)), int(match.group(3))
        month = _MONTHS.get(name.lower())
        return _date(year, month, day) if month else None
    return None


def _date(year: int, month: int, day: int) -> _Date | None:
    """A calendar date inside the workbook-plausible years, or None.

    Years outside 1900 to 2200 and impossible month/day combinations read
    as not a date, so a serial number or a typo cannot pose as one."""
    if not 1900 <= year <= 2200:
        return None
    try:
        return _Date(year, month, day)
    except ValueError:
        return None


# -- the table -------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """One column of the bounded table, with the kind it was classified as.

    `percent` records that most of the column's numbers wore a % sign, so
    display can add the unit the cells carried without re-reading them."""

    index: int
    name: str
    kind: str
    percent: bool = False


@dataclass(frozen=True)
class Table:
    """The table a tracker card carries, bounded and already classified:
    headers, string cells, and one Column per header."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    columns: tuple[Column, ...]


@dataclass(frozen=True)
class Finding:
    """One relationship, with the numbers that justify it.

    `rows` is the count of rows the measure rests on. `chart` is the shape
    the relationship itself suggests; `chart_choice` lets a stated
    preference override it. `suggested` holds the table row indices worth
    selecting for this finding.
    """

    key: str
    label: str
    text: str
    rows: int
    score: float
    chart: str
    columns: tuple[str, ...] = ()
    suggested: tuple[int, ...] = ()


def read_table(value: object) -> Table | None:
    """The bounded table a tracker card carries, or None when it has none."""
    if not isinstance(value, dict):
        return None
    headers_raw = value.get("headers")
    rows_raw = value.get("rows")
    if not isinstance(headers_raw, list) or not isinstance(rows_raw, list):
        return None
    headers = tuple(str(cell).strip() for cell in headers_raw[:MAX_COLUMNS])
    if len(headers) < 2:
        return None
    rows: list[tuple[str, ...]] = []
    for raw in rows_raw[:MAX_ROWS]:
        if not isinstance(raw, (list, tuple)):
            continue
        cells = ["" if cell is None else str(cell) for cell in raw[: len(headers)]]
        cells += [""] * (len(headers) - len(cells))
        if any(cell.strip() for cell in cells):
            rows.append(tuple(cells))
    if not rows:
        return None
    columns = tuple(_classify(headers, rows, index) for index in range(len(headers)))
    return Table(headers=headers, rows=tuple(rows), columns=columns)


def _classify(headers: tuple[str, ...], rows: list[tuple[str, ...]], index: int) -> Column:
    """One column's kind: date, number, percent-flagged number, or text.

    A kind asks for 60 percent of the filled cells (two at the least), so
    a stray number in a notes column does not turn it numeric. Dates are
    tried before numbers, and a numeric column is percent when most of
    its numbers wore a % sign."""
    name = headers[index] or f"column {index + 1}"
    cells = [row[index] for row in rows]
    filled = sum(1 for cell in cells if cell.strip())
    if filled < 2:
        return Column(index=index, name=name, kind="text")

    needed = max(2, math.ceil(filled * 0.6))
    dates = []
    numbers = []
    percents = 0
    for cell in cells:
        day = parse_date(cell)
        if day is not None:
            dates.append(day)
            continue
        number = parse_number(cell)
        if number is not None:
            numbers.append(number)
            if cell.strip().endswith("%"):
                percents += 1
    if len(dates) >= needed:
        return Column(index=index, name=name, kind="date")
    if len(numbers) >= needed:
        return Column(
            index=index,
            name=name,
            kind="number",
            percent=percents * 2 > len(numbers),
        )
    return Column(index=index, name=name, kind="text")


def _number_text(value: float) -> str:
    """A number as findings print it: thousands separated, and no trailing
    zeros after a decimal point."""
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _with_unit(value: float, column: Column) -> str:
    """A number in prose, with the % carried back when the column wore one."""
    return _number_text(value) + ("%" if column.percent else "")


def _percent_text(share: float) -> str:
    """A fraction as a percentage, gaining a decimal as it shrinks, so a
    4 percent share is not rounded away to nothing."""
    points = share * 100
    if points >= 10:
        return f"{points:.0f}%"
    if points >= 1:
        return f"{points:.1f}%"
    return f"{points:.2f}%"


def _prose_date(day: _Date) -> str:
    """A date as the findings spell it: 2024-06-01, no locale between the
    numbers and the reader."""
    return f"{day.year}-{day.month:02d}-{day.day:02d}"


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """The Pearson coefficient of two equal-length runs, or None when it
    is undefined.

    Fewer than two pairs, or no spread on either side, has no coefficient
    to compute. Sums run through fsum and the result is clamped to the
    interval from -1 to 1, so float drift cannot push a correlation past
    its own bounds."""
    count = len(xs)
    if count < 2:
        return None
    mean_x = math.fsum(xs) / count
    mean_y = math.fsum(ys) / count
    spread_x = math.fsum((x - mean_x) ** 2 for x in xs)
    spread_y = math.fsum((y - mean_y) ** 2 for y in ys)
    if spread_x <= 0 or spread_y <= 0:
        return None
    coefficient = math.fsum(
        (x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)
    ) / math.sqrt(spread_x * spread_y)
    if not math.isfinite(coefficient):
        return None
    return max(-1.0, min(1.0, coefficient))


def _band(coefficient: float) -> str:
    """The strength word a correlation's text carries: very strong, strong
    or moderate, judged on the absolute value."""
    strength = abs(coefficient)
    if strength >= 0.85:
        return "very strong"
    if strength >= 0.7:
        return "strong"
    return "moderate"


def _categorical(groups: int, rows: int) -> bool:
    """Whether a text column is a set of categories rather than identifiers.

    Two groups at the least, and never more than half the rows (three
    always allowed): a column where nearly every row is its own label
    names rows, not groups, and a near-tie between two of them would not
    be a finding."""
    return groups >= 2 and groups <= max(3, rows // 2)


def _numeric(table: Table) -> list[Column]:
    """The columns that read as numbers."""
    return [column for column in table.columns if column.kind == "number"]


def _dated(table: Table) -> list[Column]:
    """The columns that read as dates."""
    return [column for column in table.columns if column.kind == "date"]


def _textual(table: Table) -> list[Column]:
    """The columns that read as text."""
    return [column for column in table.columns if column.kind == "text"]


# -- detectors -------------------------------------------------------------


def correlations(table: Table) -> list[Finding]:
    """Pairs of numeric columns that move together at |r| >= 0.6."""
    columns = _numeric(table)
    found: list[Finding] = []
    for position, left in enumerate(columns):
        for right in columns[position + 1:]:
            xs: list[float] = []
            ys: list[float] = []
            for row in table.rows:
                x = parse_number(row[left.index])
                y = parse_number(row[right.index])
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
            if len(xs) < MIN_PAIRED or xs == ys:
                continue
            coefficient = _pearson(xs, ys)
            if coefficient is None or abs(coefficient) < MIN_CORRELATION:
                continue
            movement = (
                f"{left.name} rises with {right.name}"
                if coefficient > 0
                else f"{left.name} falls as {right.name} rises"
            )
            found.append(
                Finding(
                    key="correlation",
                    label=LABELS["correlation"],
                    text=(
                        f"{movement}: r = {coefficient:.2f} "
                        f"({_band(coefficient)}) across {len(xs)} paired rows. "
                        "Two columns that move together are one relationship to read, "
                        "not two separate totals; that is an association, not a cause."
                    ),
                    rows=len(xs),
                    score=abs(coefficient),
                    chart=AUTO_CHART["correlation"],
                    columns=(left.name, right.name),
                )
            )
    return found


def trends(table: Table) -> list[Finding]:
    """A numeric column that moves in one direction across a dated column."""
    found: list[Finding] = []
    for value_column in _numeric(table):
        for date_column in _dated(table):
            points: dict[_Date, list[float]] = {}
            used = 0
            for row in table.rows:
                day = parse_date(row[date_column.index])
                number = parse_number(row[value_column.index])
                if day is None or number is None:
                    continue
                points.setdefault(day, []).append(number)
                used += 1
            if len(points) < MIN_TREND_POINTS:
                continue
            ordered = sorted(points.items())
            means = [math.fsum(values) / len(values) for _day, values in ordered]
            if means[0] == means[-1]:
                continue
            direction = 1 if means[-1] > means[0] else -1
            steps = [second - first for first, second in zip(means, means[1:])]
            consistent = sum(1 for step in steps if direction * step >= 0)
            fraction = consistent / len(steps)
            if fraction < MIN_MONOTONIC:
                continue
            verb = "rose" if direction > 0 else "fell"
            found.append(
                Finding(
                    key="trend",
                    label=LABELS["trend"],
                    text=(
                        f"{value_column.name} {verb} from "
                        f"{_with_unit(means[0], value_column)} to "
                        f"{_with_unit(means[-1], value_column)} between "
                        f"{_prose_date(ordered[0][0])} and {_prose_date(ordered[-1][0])}: "
                        f"{consistent} of {len(steps)} steps in one direction across "
                        f"{len(ordered)} dated points. "
                        "The movement holds step by step, so the two ends describe the "
                        "range rather than one odd row."
                    ),
                    rows=used,
                    score=fraction,
                    chart=AUTO_CHART["trend"],
                    columns=(value_column.name, date_column.name),
                )
            )
    return found


def _groups(table: Table, group_column: Column, value_column: Column):
    """Label -> summed value, plus the rows behind each label, or None."""
    totals: dict[str, float] = {}
    rows: dict[str, list[int]] = {}
    used = 0
    for index, row in enumerate(table.rows):
        label = row[group_column.index].strip()
        number = parse_number(row[value_column.index])
        if not label or number is None:
            continue
        if number < 0:
            return None, None, 0
        totals[label] = totals.get(label, 0.0) + number
        rows.setdefault(label, []).append(index)
        used += 1
    return totals, rows, used


def shares(table: Table) -> list[Finding]:
    """One group that carries at least half of a numeric column's total."""
    found: list[Finding] = []
    for group_column in _textual(table):
        for value_column in _numeric(table):
            if value_column.percent:
                continue
            totals, rows, used = _groups(table, group_column, value_column)
            if not totals or not _categorical(len(totals), used):
                continue
            if len(totals) < MIN_GROUPS:
                continue
            total = math.fsum(totals.values())
            if total <= 0:
                continue
            top, top_value = max(totals.items(), key=lambda item: (item[1], item[0]))
            share = top_value / total
            if share < MIN_TOP_SHARE:
                continue
            found.append(
                Finding(
                    key="share",
                    label=LABELS["share"],
                    text=(
                        f"{top} is {_percent_text(share)} of {value_column.name}: "
                        f"{_with_unit(top_value, value_column)} of "
                        f"{_with_unit(total, value_column)} across {used} numbered rows "
                        f"in {len(totals)} groups. "
                        "The total is carried by one group, so read the split before the sum."
                    ),
                    rows=used,
                    score=share,
                    chart=AUTO_CHART["share"],
                    columns=(group_column.name, value_column.name),
                    suggested=tuple(rows.get(top, [])[:5]),
                )
            )
    return found


def ratios(table: Table) -> list[Finding]:
    """Two top groups within 1.5x of each other: a split, not a leader."""
    found: list[Finding] = []
    for group_column in _textual(table):
        for value_column in _numeric(table):
            if value_column.percent:
                continue
            totals, rows, used = _groups(table, group_column, value_column)
            if not totals or used < MIN_RATIO_ROWS:
                continue
            if not _categorical(len(totals), used) or len(totals) < 2:
                continue
            ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
            (first, first_value), (second, second_value) = ranked[0], ranked[1]
            if first_value <= 0 or second_value <= 0:
                continue
            ratio = first_value / second_value
            if ratio > MAX_RATIO:
                continue
            score = (MAX_RATIO - ratio) / (MAX_RATIO - 1.0)
            found.append(
                Finding(
                    key="ratio",
                    label=LABELS["ratio"],
                    text=(
                        f"{first} and {second} are within {ratio:.1f}x of each other: "
                        f"{_with_unit(first_value, value_column)} against "
                        f"{_with_unit(second_value, value_column)} across {used} rows "
                        f"in {len(totals)} groups. "
                        "A split this even means neither side carries the range, "
                        "so the pair is the story."
                    ),
                    rows=used,
                    score=max(0.0, min(1.0, score)),
                    chart=AUTO_CHART["ratio"],
                    columns=(group_column.name, value_column.name),
                    suggested=tuple((rows.get(first, []) + rows.get(second, []))[:5]),
                )
            )
    return found


def _row_name(table: Table, index: int, label_column: str | None) -> str:
    """The name an outlier's row goes by in its finding.

    The tracker's chosen label column wins; otherwise the row's first
    non-numeric cell, and only when the row is nothing but numbers does
    the finding fall back to \"row N\"."""
    if label_column:
        for column in table.columns:
            if column.name.lower() == label_column.strip().lower():
                cell = table.rows[index][column.index].strip()
                if cell:
                    return cell[:40]
    for column in table.columns:
        if column.kind != "number":
            cell = table.rows[index][column.index].strip()
            if cell:
                return cell[:40]
    return f"row {index + 1}"


def outliers(table: Table, label_column: str | None = None) -> list[Finding]:
    """One row 2.5 standard deviations from its column's average."""
    found: list[Finding] = []
    for column in _numeric(table):
        points = [
            (index, parse_number(row[column.index]))
            for index, row in enumerate(table.rows)
        ]
        points = [(index, value) for index, value in points if value is not None]
        if len(points) < MIN_OUTLIER_POINTS:
            continue
        values = [value for _index, value in points]
        mean = math.fsum(values) / len(values)
        deviation = math.sqrt(math.fsum((value - mean) ** 2 for value in values) / len(values))
        if deviation <= 0:
            continue
        index, value = max(points, key=lambda item: (abs(item[1] - mean), -item[0]))
        z_score = (value - mean) / deviation
        if abs(z_score) < MIN_Z:
            continue
        side = "above" if z_score > 0 else "below"
        found.append(
            Finding(
                key="outlier",
                label=LABELS["outlier"],
                text=(
                    f"{_row_name(table, index, label_column)} is {abs(z_score):.1f} standard "
                    f"deviations {side} the {column.name} average of "
                    f"{_with_unit(mean, column)} "
                    f"({_with_unit(value, column)}) across {len(points)} rows. "
                    "One row that far out bends any average or trend drawn from this range, "
                    "so read it first."
                ),
                rows=len(points),
                score=abs(z_score),
                chart=AUTO_CHART["outlier"],
                columns=(column.name,),
                suggested=(index,),
            )
        )
    return found


# -- the reading -----------------------------------------------------------


def findings(table: Table, label_column: str | None = None) -> list[Finding]:
    """Every relationship the table supports, strongest first."""
    found = [
        *trends(table),
        *correlations(table),
        *shares(table),
        *ratios(table),
        *outliers(table, label_column),
    ]
    # A share and a near-tie over the same pair say the same thing twice;
    # the share is the larger claim and keeps its place.
    shared = {finding.columns for finding in found if finding.key == "share"}
    kept = [
        finding
        for finding in found
        if not (finding.key == "ratio" and finding.columns in shared)
    ]
    return sorted(
        kept,
        key=lambda finding: (
            STRENGTH.index(finding.key),
            -finding.score,
            finding.columns,
        ),
    )


def chart_choice(finding: Finding, preference: str = "auto") -> tuple[str, str]:
    """The shape to draw and the sentence that says why.

    Returns (shape, sentence). A stated preference other than `auto` wins
    over the shape the relationship suggests, and the sentence says so
    plainly, so the user can disagree with either.
    """
    natural = AUTO_CHART.get(finding.key, "table")
    chosen = preference if preference in ("bar", "line", "table") else "auto"
    if chosen == "auto":
        sentence = f"{_CHART_NOUN[natural].capitalize()} fits this: {_CHART_REASON[natural]}."
    elif chosen == natural:
        sentence = (
            f"Your chart setting asks for {_CHART_NOUN[chosen]}, and it fits: "
            f"{_CHART_REASON[natural]}."
        )
    else:
        sentence = (
            f"Your chart setting asks for {_CHART_NOUN[chosen]}, so use that; left alone "
            f"this reading would draw {_CHART_NOUN[natural]}, because "
            f"{_CHART_REASON[natural]}."
        )
    return (natural if chosen == "auto" else chosen), sentence
