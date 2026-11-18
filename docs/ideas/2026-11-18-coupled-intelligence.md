# 20 ideas that make the desk feel like it knows you

Written 2026-11-18 for the coupled-intelligence round. The five behaviours the
brief named are the first slice; these are the next twenty, in descending
strategic value. Every one of them assumes the same primitive: **the desk holds
a private, user-owned model of that person's work** — their people, projects,
commitments, preferences and history — and every surface is allowed to read it.
None of them is a prompt; each is a product loop that gets better every week the
user keeps the desk open, which is exactly the compounding a competitor cannot
copy by shipping a feature.

Scoring legend — **M**oat (1-5, how much it compounds with use), **E**ffort
(S/M/L for the thin version), **Reach** (how many cards/users it touches).

| # | Idea | M | E | Reach |
|---|------|---|---|-------|
| 1 | Commitments ledger | 5 | L | mail, calendar, digest |
| 2 | What changed since you last looked | 5 | S | every card |
| 3 | The counterfactual card | 5 | M | workbook, targets |
| 4 | Personal entity graph (your ontology) | 5 | M | all plugins |
| 5 | Relationship-weighted inbox | 4 | M | digest, waiting-on-you |
| 6 | Voice-matched drafting with consent | 4 | L | mail |
| 7 | Meeting → outcome loop | 5 | L | calendar, notes |
| 8 | Desk-wide question answering | 4 | M | all |
| 9 | Interrupt budget and quiet hours | 4 | S | every nudge |
| 10 | Decision journal and calibration | 5 | M | workbook, research |
| 11 | Research that argues back | 4 | S | research |
| 12 | Anomaly → cause → action | 4 | M | workbook |
| 13 | Stakeholder churn radar | 4 | L | mail, workbook |
| 14 | Monday memo (chief of staff) | 5 | M | digest, all |
| 15 | Preference autopilot with receipts | 4 | S | settings |
| 16 | Attention vs value portfolio | 4 | M | calendar, workbook |
| 17 | Provenance-first trust surface | 4 | S | every claim |
| 18 | Meetings that pre-mortem themselves | 3 | M | calendar |
| 19 | Adaptive plugin marketplace | 3 | M | marketplace |
| 20 | The desk that answers the email you didn't send | 3 | M | mail |

## 1. Commitments ledger
Every "I'll send it Friday", "let me check with Priya", "we owe them a revised
quote" becomes a row with an owner, a date and a source. Mine it from mail
threads, meeting notes and workbook comments; reconcile it against what actually
happened; surface only what is at risk. **Moat:** a competitor can copy the
extraction, not the three years of commitments already reconciled. **Thin
version:** extract from the top three threads daily into an approval inbox, one
card of "promises you made that are due".

## 2. What changed since you last looked
The dashboard already knows every previous payload. Diff them perceptually, not
numerically: the field that moved, the thread that went quiet, the meeting that
moved two hours, the column that appeared in the sheet. One line per card, at
the top, in the order the user cares. **Moat:** requires persistence plus a
model of salience; pure front-end dashboards cannot do it. **Thin version:** the
delta line on each card, computed against the last read the user saw, not the
last poll.

## 3. The counterfactual card
Invert the tracker: "to hit 120 by the 30th you need 4.2 per remaining day, and
your last four weeks averaged 2.1 — the gap is EMEA's pipeline". The maths is
trivial; the reason it is rare is that nobody keeps the history to say it
honestly. **Thin version:** required rate vs trailing rate vs named gap column.

## 4. Personal entity graph
People, companies, projects, files, deals — one editable graph the user can
correct, that every plugin reads. Not a knowledge graph for its own sake: it is
the join key that lets a calendar event, an email and a workbook column talk
about the same "Acme". **Thin version:** an entity list built from mail senders
and calendar attendees, user-correctable, used by three readings.

## 5. Relationship-weighted inbox
Priority = f(waiting age, relationship strength from the entity graph, commitment
proximity, the user's own response-time history with that person). Replaces the
flat score with a model of the relationship. **Thin version:** weight by
per-sender response history, which the desk can already observe.

## 6. Voice-matched drafting with consent
A style profile built only from mail the user explicitly contributed: greeting,
sentence length, sign-off, the words they never use. Drafts stop sounding like a
language model. **Thin version:** three tone presets plus the user's own
greeting and sign-off, offered as a draft in the existing writer.

## 7. Meeting → outcome loop
Every meeting ends in decisions and commitments; every future meeting card opens
with the ones still unresolved from the last three meetings with those people.
This is the single highest-value loop in the product: it makes the desk the
memory of the calendar. **Thin version:** one "open loops from the last meeting"
line, extended by hand.

## 8. Desk-wide question answering
"Which customers got worse this quarter and who did I promise what?" answered as
a card built from workbook, mail and memory together — not a chat reply.
**Moat:** requires the joins in #4. **Thin version:** three canned questions over
the tracker plus memory recall.

## 9. Interrupt budget and quiet hours
The desk has a weekly interruption allowance, spent by whatever it decides to
raise, refilled weekly; the user sets quiet windows. Everything that wants
attention competes for a scarce resource instead of stacking up.
**Thin version:** a per-card "raise at most once a day" rule plus quiet hours.

## 10. Decision journal and calibration
Record a decision, the expectation, the date to check. Later, score it. Over a
year the desk can tell the user "your revenue forecasts run 18% high" — the kind
of self-knowledge no spreadsheet gives. **Thin version:** decisions captured from
the workbook's confirm step, with one check-back reminder.

## 11. Research that argues back
After an answer, the desk names the strongest piece of evidence that would
falsify it, and offers to fetch exactly that. Turns research from confirmation
into a falsification loop. **Thin version:** one "what would change my mind" line
on the research card, generated deterministically from the answer's claims.

## 12. Anomaly → cause → action
An outlier row is only interesting with a cause. The desk proposes the two
columns that explain it (a price change, a segment shift), and one action to
take. **Thin version:** outlier detection plus the segment that moved most.

## 13. Stakeholder churn radar
Quiet is a signal: a contact whose cadence drops 60% while their account's
numbers soften is a churn risk months before it is a renewal problem.
**Thin version:** per-contact last-contact age versus the user's own median,
pinned to the three biggest accounts.

## 14. Monday memo
One narrative, chief-of-staff voice, seven minutes: what moved, what is at risk,
what you promised, what to decide this week, what to read before Tuesday's
board call. The single artifact that makes the desk feel like a person works
there. **Thin version:** assemble the week's card readings into one page, in the
desk's editorial voice, deterministic.

## 15. Preference autopilot with receipts
The desk proposes preference changes it noticed ("you always switch charts to
line — make it the default?") and never applies them without a press. Every
applied change keeps a receipt and a one-click undo. **Thin version:** count the
user's manual overrides and propose the most frequent one.

## 16. Attention vs value portfolio
Where the hours went (calendar) against where the numbers moved (workbook). Not
a productivity score — a portfolio view: "38% of your time on accounts that
produced 6% of bookings". **Thin version:** two-column card, month to date.

## 17. Provenance-first trust surface
Every derived sentence carries a one-click "why": which cells, which memory
facts, which rule. This is the feature that makes the rest sellable inside a
company with a compliance officer. **Thin version:** the source list already on
the payload, rendered as a footnote.

## 18. Meetings that pre-mortem themselves
Before a meeting, the desk asks the three questions most likely to derail it,
drawn from the deal's own history ("they asked twice about security; nobody owns
the answer"). **Thin version:** one prompt derived from unanswered questions in
the thread.

## 19. Adaptive plugin marketplace
Recommend a plugin from the shape of the user's own data: three date columns and
a amounts column suggests a burn view; a mail volume spike suggests a
triage plugin. **Thin version:** a data-shape scan that ranks three installed-
able plugins.

## 20. The desk that answers the email you didn't send
The inverse of a reminder: the desk drafts the message the user has been
avoiding — the apology, the chase, the no — in their voice, and leaves it in the
writer. It is the one place where the product earns the word "assistant".
**Thin version:** detect the thread with the longest draft-less avoidance and
offer one skeleton.

## How I would pick

- **Cheapest compounding:** #2 (what changed), #15 (preference receipts), #17
  (provenance) — small, but they make everything else feel trustworthy.
- **Highest defensibility:** #1 (commitments), #7 (meeting loop), #14 (Monday
  memo) — the three that turn months of use into an asset.
- **Sharpest single demo:** #3 (counterfactual) and #20 (the email you didn't
  send).
- **Do not build yet:** #6 (voice) and #13 (churn) need data the desk does not
  yet keep; #19 depends on a marketplace with enough supply.
