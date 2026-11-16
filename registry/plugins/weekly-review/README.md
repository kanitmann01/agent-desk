# Weekly Review

**Question:** where did the week stall, and what needs attention?

## What it reads

One `aggregate` source over `sales-delta-widget`, `follow-up-watch`,
`week-load` and `plugin-health`.

The host implements `sum`, `count`, `latest`, `min` and `max`. These cards
do not share a unit, so the plugin uses **count**: members that supplied a
numeric value, with one row per contributor. Nothing is summed across
unlike units.

A missing member is named (`missing-dependency`); an installed but blank
member is named (`blank-dependency`). No estimate fills the gap.

## Elements

| element | binding | shows |
|---|---|---|
| metric "Sources live" | `value` | number of members reporting a value |
| list "Stalled" | `rows` | one row per reporting member |
