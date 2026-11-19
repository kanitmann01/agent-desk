# Morning Brief

**Question:** what matters today, in one card?

## What it reads

One `aggregate` source over four dependencies: `sales-delta-widget`,
`calendar-today`, `outlook-digest` and `research-brief`.

The host implements `sum`, `count`, `latest`, `min` and `max`. These four
cards do not share a unit, so the plugin uses **count**: how many members
supplied a numeric value, with one row per contributor. It never invents a
cross-card total.

All four members must be installed and readable. A missing member renders
blank with the named `missing-dependency` reason; an installed but blank
member renders blank with `blank-dependency`. No zero, no placeholder.

## Elements

| element | binding | shows |
|---|---|---|
| metric "Live metrics" | `value` | number of members reporting a value |
| list "Today" | `rows` | one row per reporting member |
