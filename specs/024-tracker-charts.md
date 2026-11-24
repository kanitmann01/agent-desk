# Spec 024: A tracker tile that follows a metric over time

Status: ready-for-agent (2026-11-24). Filed as #295. Tickets: #296, #297, #298.
`GLOSSARY.md` is the vocabulary.
The setup sheet and the tracker reading are the seams; no new seam.

## Problem Statement

A manager who tracks a team's KPIs can attach a workbook, but the tracker
tile only remembers one total. Each time the desk re-reads the file it
appends that total, and the tile draws those re-reads as a line. The
workbook's own weeks, sprints, or dates are ignored, even though a time
column can already be saved. The manager cannot choose a line, columns,
or an area, and the setup sheet shows a bar wireframe that does not
change with the choice.

Suggesting what to track is a separate button. It asks the insights place
on Your AI, and it names only a label and a value. With a key saved, the
desk should look at the columns itself and offer the whole setup. One
click accepts it. The same sheet still lets the manager pick by hand.

## Solution

On the setup sheet the manager picks a metric, an optional time column,
and a chart: a line, columns, or an area. A skeleton of that chart sits
on the sheet and changes as the choice changes.

When a time column is chosen, the tile plots the workbook. Rows that
share a period collapse with the chosen aggregate. The big number is the
latest period, and the change is against the previous period. When no
time column is chosen, the tile keeps today's total and the history of
re-reads, drawn in the chosen chart.

When Your AI has a key, opening the columns step asks the desk's default
model once. The suggestion names the metric, the time column, the chart,
and the aggregate. Accept fills those controls and moves to the name
step. It does not save by itself. With no key, nothing is sent and the
sheet is manual. Changing a control clears the suggestion.

## User Stories

1. As a manager, I want to attach a workbook and choose the metric column, so that the tile follows the KPI I care about.
2. As a manager, I want to choose a time column, so that the tile plots the weeks or dates in the file rather than the times the desk re-read it.
3. As a manager, I want to leave the time column empty, so that a workbook with no dates still tracks one total the way it does today.
4. As a manager, I want to choose a line, columns, or an area, so that the shape matches the KPI.
5. As a manager, I want a skeleton of that chart on the setup sheet, so that I can see the shape before I save.
6. As a manager, I want the skeleton to name the metric, the time column or "each reading", and the chart, so that I know what I am about to save.
7. As a manager, I want the skeleton to update when I change the chart, the metric, or the time column, so that it never shows a stale choice.
8. As a manager, I want the skeleton to stay on the name step, so that I still see the choice while I name the tracker.
9. As a manager, I want several rows in one period to collapse with sum, count, latest, min, or max, so that a team sheet becomes one point per period.
10. As a manager, I want the big number to be the latest period, so that the tile shows the current KPI and not the sum of every week.
11. As a manager, I want the change to compare the latest period with the previous one, so that the tile says how the KPI moved.
12. As a manager, I want dates the desk already treats as the same day to land in one period, so that `03/01/2026` and `2026-01-03` do not become two points. `1/3/2026` stays 1 March, because the desk reads day-first text before month-first text.
13. As a manager, I want labels like `Sprint 14` to stay in the order they appear in the file, so that a sheet that is not calendar dates still reads in order.
14. As a manager, I want blank time cells skipped, so that an empty cell does not become a period.
15. As a manager, I want at most the newest sixty periods on the chart, so that a long sheet still fits the tile, and I want the tile to say when older periods were left off.
16. As a manager, I want a missing time column to fall back to the history of re-reads, so that a renamed column does not invent dates, and I want the tile to say the column is gone.
17. As a manager, I want an empty time column to leave the dotted wireframe, so that a choice with no points does not draw a fake chart, and I want a sentence that says there are no points.
18. As a manager, I want checking rows to limit which rows are counted, so that I can follow one person on a team sheet.
19. As a manager, I want accepting a suggestion to count every row, so that five sample rows are not mistaken for the whole sheet.
20. As a manager, I want no rows checked to mean every row in the read, so that I do not have to tick a long sheet.
21. As a manager with a key saved, I want the columns step to suggest a metric, a time column, a chart, and an aggregate without a separate button, so that the usual choice is one click.
22. As a manager, I want Accept to fill those controls and take me to the name step, so that I still name the tracker and can still accept a file that lives outside the workspace folder.
23. As a manager, I want to ignore the suggestion and pick by hand on the same sheet, so that a wrong suggestion does not block me.
24. As a manager, I want the first edit of a control to clear the suggestion, so that the sheet does not keep offering a choice I have already changed.
25. As a manager, I want the skeleton to switch when I accept a suggestion, so that the shape matches what Accept just filled in.
26. As a manager with no key, I want no suggestion and no columns sent anywhere, so that setup stays on this machine.
27. As a manager, I want a failed model call to fall back to a suggestion made on this machine, so that a bad reply still offers a starting point and says it was made locally.
28. As a manager, I want a suggestion that names a column the file does not have to drop that part, so that Accept cannot point at a missing column.
29. As a manager, I want the time column and the metric to be different columns, so that a period is not plotted against itself.
30. As a manager who already has a tracker with no time column, I want the tile to keep its total, its change since the last reading, and its line, so that this work does not move numbers I already trust.
31. As a manager, I want the setup sheet's marketplace cousin to keep requiring a row selection, so that only the tracker treats an empty selection as every row.

## Implementation Decisions

The tracker stays one tile and one series. A second line per person is
not this spec. Wide sheets, where the dates are the column headers, are
not read. Pie, stacked, and scatter charts are not offered. No chart
library.

The desk-wide chart preference (auto, bar, line, table) still only
changes the sentence under a reading. The chart on the tile is stored
on that tracker's own choice.

Stored choice, added to the column choice that already keeps a time
column:

- `chart` is `line`, `column`, or `area`. Omitted means `line`.
- A blank time column is stored as none.
- A time column equal to the value column, ignoring case, is refused.
- Any other `chart` value is refused.
- Aggregate stays sum, count, latest, min, or max.

Reading, when a time column is set:

- Read up to 5000 data rows. A tracker with no time column still reads
  the first 500, so its total does not change.
- A row list limits the rows. None means every row in that window.
- Bucket by the time cell. Dates the desk already parses (ISO text,
  common day-first and month-first text, Excel serials) become
  `YYYY-MM-DD`, so two writings of the same day merge. Anything else
  keeps its trimmed text. Blank cells are skipped.
- If every kept bucket is a date, sort by the date. Otherwise keep the
  first-seen order of the file.
- Reduce each bucket with the stored aggregate. The value is the latest
  bucket. The change is latest minus previous, and the tile says
  "since the previous period".
- The chart receives at most the newest 60 buckets. The foot notes when
  older ones were dropped.
- A time column that is no longer a header falls back to the re-read
  history and the foot says the column is missing.
- A time column with no buckets leaves the value at 0, draws no chart,
  and the foot says there are no points.
- The re-read history may still record the headline, so clearing the
  time column later has a past. The points on a time chart are the
  buckets, not that history.

Reading, when no time column is set: today's total, today's re-read
history (last 30, append only when the total changed), and the change
"since the last reading". The chosen chart still draws those points.

The tile payload gains `chart`, `axis` (`time` or `reading`), `labels`
aligned with the numeric points, `deltaLabel`, and `seriesNote`. Points
stay a list of numbers. The line element under the reading stays for a
line chart. Columns and area are drawn by the tile, not as new element
kinds.

Setup sheet:

- The shared workbook walk gains one switch, default off: an empty row
  selection is allowed and means every row. Only the tracker turns it
  on. The marketplace sheet does not.
- Time column, chart, and aggregate sit on the columns step with the
  grid. Name and unit stay on the name step.
- The skeleton uses the existing dotted wireframe and a fixed
  silhouette, not the workbook's numbers. Columns reuse the bar wire.
  A line is a dotted polyline through the same heights. An area is that
  polyline with a quiet fill to the baseline. Its accessible name is
  the caption. It is not inside the open-step decoration that
  disappears on a narrow window; on a narrow sheet it stacks above the
  grid.
- The open step's decoration becomes the line skeleton, because line is
  the default.
- Continue no longer asks the model to review the choice. The review
  route stays. The tracker sheet stops calling it.

Suggestion:

- The tracker asks the default model: the default binding, else the
  single saved AI connection, else the environment key. Not the
  insights place. No new setting.
- Unbound means the route returns no proposal and the sheet does not
  call. The Suggest button goes away.
- The request is unchanged: the one-sentence job, the sheet name, the
  headers, and at most five rows, capped at 8 KiB. The file path stays
  on the machine. The headers-only setting still drops the rows. The
  strip shows the disclosure, because the send is no longer behind a
  button.
- The reply is one JSON object: label column, value column, time column
  (a header, or null), chart, aggregate, and a reason. A bad chart
  becomes `line`. A time column that is not a header, or that equals
  the value column, becomes null. A bad aggregate becomes sum. Row
  indexes in the reply are ignored.
- Accept fills the controls, marks the save as suggested, sends every
  row, and moves to the name step.
- If the call fails after a key was present, the on-this-machine
  heuristic proposes instead and says so. It picks a time column when
  most of that column's sampled cells parse as dates, and it picks a
  line when it found one and columns when it did not.
- One request per opened preview. Closing the sheet and opening a file
  again asks again.

Edit still starts from the open step and does not preload the saved
choice.

## Testing Decisions

Test behaviour at the seams that already exist. Do not add a route or a
harness.

A good test asserts the reading a tracker returns, the proposal a
suggestion returns, and what the setup sheet posts and shows. It does
not assert private helpers, SVG path strings, or how many times a
component function ran.

- The tracker reading tests already open a workbook, confirm a choice,
  and read it back. Extend those: a weekly sheet with two people on the
  same date becomes one point per week and the value is the latest
  week; equivalent date text merges; sprint labels stay in file order;
  a missing time column falls back; a bad chart is refused; an omitted
  chart is stored as a line. The existing "second reading is a signed
  change" test stays green.
- The suggestion tests already feed a model reply and a small table.
  Extend those: a time column and an area chart are kept; an unknown
  chart becomes a line; a time column that is not a header becomes
  null; row indexes in the reply are not applied. The on-this-machine
  proposal picks a date-like column when the sample parses.
- The setup sheet tests already open a workbook through the tile and
  post a confirm. Extend those: a confirm with a time column, columns
  as the chart, and no rows posts a null row list; arriving on the
  columns step requests a suggestion without a Suggest press; Accept
  fills the controls; with no proposal the sheet still confirms; the
  skeleton's accessible name names the chart and changes when the
  chart control changes and when an area suggestion is accepted.
- The tile tests already render a reading. Extend those: a time-axis
  column chart's accessible name includes the first and last labels; a
  reading with no chart still draws a line from its points.

## Out of Scope

- One line per person, or any split other than the row checkboxes.
- Dates as column headers.
- Pie, stacked, dual-axis, or a chart library.
- Changing the desk-wide chart preference.
- Preloading a saved choice when Edit opens.
- Teaching the no-JavaScript element list to draw columns or an area.
- Picking a sheet other than the one the preview already uses.
- Raising the 500-row cap on trackers that have no time column.

## Further Notes

The five rows the model sees are a sample. Treating them as the rows to
track would save a tracker of the sample. Accept always means every row;
the manager limits the rows by checking them.

The skeleton is a silhouette of the chart kind. The sheet has only the
top of the file, so plotting those rows would not match the tile that
gets saved.
