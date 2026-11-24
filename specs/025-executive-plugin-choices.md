# Spec 025: Executive choices when creating a plugin

Status: ready-for-agent (2026-11-24). `GLOSSARY.md` at the repo root is the
vocabulary; the user-facing word for a plugin on the home screen is "tile".

## Problem Statement

Describing a plugin in plain English produces the same thing every time: a
workbook tracker showing one number. The wizard asks three questions, and no
matter what is answered it composes a single metric card. Its default source is
the workbook, so answering one question and submitting fills the rest with the
workbook.

The desk can already read eleven sources — workbook, CSV, JSON, notes, a web
page, the calendar, the mail folder, a hand-kept number, desk state, research,
and composed comparisons — and can already draw ten card shapes. The wizard
uses one of each.

The manager is also never told when their tile will update. A schedule is
written into the installed plugin and never run. There is no hook that
re-refreshes a tile when the workbook is saved, mail arrives, or the calendar
changes. So "when it updates" is not a choice a manager can make, and the tile
is only ever read when the home screen is drawn.

Finally, the manager has already said what they want in a sentence. Making them
answer four questions to restate it is wasted work when the desk has an AI
connection that could read the sentence and fill the fields for them.

## Solution

Describing a plugin now asks what the tile watches, what it shows, how it looks,
and when it updates, and then builds exactly that. When an AI connection is
saved, the sentence fills those fields before the questions are asked, inside a
dialog that shows the fill happening, and says plainly that it filled them in.

"Add an AI connection to fill these in from your description next time" is the
quiet line a manager without one sees, in place of today's error-style alert.

The three update choices — when the home screen is opened, on a clock, when the
watched thing changes — each refresh the tile for real.

## User Stories

1. As a manager, I want to choose what my new tile watches from the desk's real
   sources, so that I can build a tile for my mail or my calendar and not only
   for a spreadsheet.
2. As a manager, I want the source choices to be named in business words ("my
   mail", "a web page", "a number I keep"), so that I do not have to know what a
   data source type is.
3. As a manager, I want to choose what the tile shows — a figure, how it moved,
   whether it is on track, or the rows behind it — so that the tile answers the
   question I actually have.
4. As a manager, I want only the things my source can actually show to be
   offered, so that I never pick an option that comes back blank.
5. As a manager, I want to choose how the tile looks — a big number, a bar, a
   short trend, a table, a list, a timeline, a checklist, or a colored status —
   so that a target reads like a target and a to-do list reads like a list.
6. As a manager, I want a question skipped when only one answer is possible, so
   that I am not asked a question with one legal answer.
7. As a manager, I want to choose when the tile updates: when I open the desk,
   on a clock time, or when the thing I watch changes, so that I know how fresh
   what I am reading is.
8. As a manager, I want a tile set to a morning clock to still show something
   when I first install it, so that I am not looking at an empty tile until
   tomorrow morning.
9. As a manager, I want a tile set to update when a workbook changes to refresh
   after I save the workbook, so that "updated when it changes" is true.
10. As a manager, I want a mail tile set to update when mail arrives to refresh
    after a mail poll that found something new, and not to re-read on every
    dashboard draw.
11. As a manager, I want a calendar tile set to update on a change to refresh
    when the calendar file changes, so that my day view is current.
12. As a manager, I want a research tile to refresh when a new research answer
    is saved, so that it follows my research.
13. As a manager, I want never to be offered "when it changes" for a web page or
    a desk fact that has no event I could watch, so that I am not promised an
    update that cannot fire.
14. As a manager, I want a hand-kept number tile to give me a small form to save
    a value, so that a manual metric is not a broken tile.
15. As a manager, I want a "Re-test now" action on every tile regardless of its
    update choice, so that I can force a fresh read when I want one.
16. As a manager, I want to describe my tile in one sentence and have the desk
    fill in the four choices for me, so that I do not restate what I already
    said.
17. As a manager, I want to see that the desk is filling those fields — a
    skeleton for each choice rather than a frozen screen — so that I know it is
    working and not stuck.
18. As a manager, I want the desk to tell me it filled the fields in from my
    description and to invite me to correct it, so that an autofill is never
    silently presented as my own answer.
19. As a manager, I want to change any autofilled field before continuing, so
    that the tile is mine and not the model's.
20. As a manager, I want the autofill to name a plugin I would not have known
    how to build, so that the sentence is doing real work.
21. As a manager without an AI connection, I want a quiet line telling me to add
    one so the next description fills itself in, instead of an error, so that I
    am not made to feel something is broken.
22. As a manager without an AI connection, I want the questions to work exactly
    as they do now, so that the wizard is fully usable offline.
23. As a manager without an AI connection, I want the line to take me straight
    to adding one, so that I can set it up in one step if I choose.
24. As a manager, I want the autofill to make no difference to what the plugin
    is allowed to read or reach, so that a model can never widen a plugin's
    permissions.
25. As a manager, I want an autofill that fails to leave the questions empty and
    answerable rather than installing anything, so that a bad model reply never
    becomes a plugin.
26. As a manager, I want a web address or a file pattern still typed by me when
    the autofill cannot infer it, so that the one detail only I know is not
    guessed.
27. As a security reviewer, I want the autofill constrained to the same closed
    vocabulary as the questions, so that the model cannot introduce a source
    type, an element kind, or an activation event outside it.
28. As a security reviewer, I want the autofill call recorded as the existing
    wizard model row, so that no new audit surface appears.
29. As a manager, I want the wizard to stop refusing my mail tile as
    "sending mail", so that my mail is a source and not an unsupported request.
30. As a manager, I want the preview to name the update choice in the same words
    I chose, so that I know what I am approving.

## Implementation Decisions

### Vocabulary closure

The wizard keeps a closed vocabulary for sources, shows, manners, and update
modes. Every question option and every autofilled value is one member of it.
The autofill may only pick member labels; anything else is dropped. This is the
same confinement the wizard already applies to its drafted manifest.

Sources are the ten the desk can read: workbook, CSV, JSON, notes, web page,
calendar, mail, hand-kept number, and research. Composed sources (compare,
aggregate) are out of vocabulary because each needs two sources and a question
the manager cannot answer without naming both; the registry keeps authoring
those. Desk state (runtime, audit, policy) is out too: the plugin runtime is
built without the host callbacks that source needs, so offering it would build
a tile that is always blank. It stays registry-authored until the runtime is
handed those callbacks.

The unbuildable rule that treats any mention of mail as "sending mail" is
narrowed to sending or drafting mail. Reading mail is a source.

### Questions

Questions are fixed and ordered, and each one's options depend on the answers
before it. A question whose path has only one legal answer is skipped rather
than asked. Nothing is built until every question on the chosen path has an
answer; the current behaviour of filling unanswered questions from defaults and
building immediately is removed.

A detail step asks for the one thing the chosen source needs and no other source
can infer: the web address for a web page, and a short workspace pattern for
CSV, JSON, and notes. A pattern written in the description is used when the
manager does not choose one.

### Composition

The composer writes one widget: its data source type is the chosen source, its
ui-schema contains only the chosen element, and its activation events are
`onWidget` plus either one `onSchedule` entry or one `onHook` entry.

The workbook keeps its config-backed shape and its existing file-and-columns
setup. Mail, calendar, research, and desk state keep their pipeline and
callback readers and name no watched file.

The hook topic is one of workbook, file, calendar, mail, research, manual. It is
derived from the source, never chosen by the manager.

### Card face

A confirmed workbook instance currently always renders the classic tracker face
(value, change, workbook, trend). It will render the face the ui-schema asks
for. The classic face stays available as one of the manners, and the setup card
and the tracker sheet keep working unchanged.

A hand-kept number gets a small save form on its tile writing the object the
manual reader already reads; until a value exists the tile stays blank with the
reader's existing reason.

### Refresh

A refresh seam beside the plugin runner holds the last reading per plugin and
answers the card from it or from a live read, according to the plugin's mode.

- Opened: no stored reading; each home-screen build reads live, as today.
- Clock: the card serves the stored reading and its as-of time. A minute-scaled
  background tick refreshes plugins whose most recent scheduled time has passed
  since their last refresh. The install takes one reading so the tile is not
  empty until the first tick.
- Change: the card serves the stored reading, replaced only when the matching
  event fires. Workbook changes come from the existing workbook change hook;
  calendar and mail from the end of their existing polls, and only when the
  reading differs from the stored one; research from the save after a successful
  answer; files and the hand-kept number from a modification-time check on the
  same minute tick.

A clock or change plugin must never be re-read merely because the home screen
was opened, or the three modes collapse into one. Re-testing still forces one
read on purpose.

### Autofill

The autofill uses the same resolved AI connection the wizard already uses for
its questions and repair, on the default job. When nothing resolves, the
autofill does not run.

The request returns the chosen label for each field plus one short reason per
field, bounded by the existing copy limits. The reply is parsed through the same
tolerant JSON reader the wizard already uses. Each returned label is checked
against the legal set for that field; a rejected field stays unanswered for the
manager. A rejected source falls back to the questions, never to the workbook.
The reasons are copy for the fill screen and are stored beside the answers, not
inside them: an answer map holds labels the composer reads, never prose.

The endpoint's answer is advisory in the same sense the manifest suggestion is:
it may name labels and prose, and nothing else. Permissions, identity, version,
and the data-source type continue to come from the composer after the manager
continues.

### Surface

The describe control on the Plugins page becomes a short text field and its
button. Without script it posts straight into the question walk, as today.

With a connection saved, submitting opens the desk's existing dialog shell with
one skeleton row per field. When the fill lands each row becomes the chosen
label and its reason, and the dialog states that the fields were filled from the
description and invites correction. Continuing builds the preview; nothing is
installed by the fill.

Without a connection, the dialog does not open. The question walk replaces the
current "No AI is saved" alert with one quiet line inviting the manager to add
an AI connection so the next description fills itself in, linking to the
connections card in Settings. The questions remain answerable.

A selected connection that fails is a separate state from no connection: the
dialog says the fill did not run and shows empty, answerable questions, and does
not suggest adding a connection the manager already has.

## Testing Decisions

A good test here drives the wizard through its public entry points and asserts
what a manager would see: which options a step offers, what the installed
manifest and ui-schema contain, and what the tile shows. Tests do not assert on
private helper names or intermediate prompt text.

Seams, highest first:

1. The real server with a scripted model: start a wizard, answer, approve, read
   the installed plugin and its card. This covers the questions, the composition,
   the autofill, and the installed result in one path.
2. The wizard compiler directly, for the vocabulary closure: which options a
   source offers, which fields survive a label outside the set, and which update
   modes each source admits.
3. The plugin runner and refresh seam with an injected clock and an injected
   event source, for the three update modes. Injected clock and event are the
   existing test seams for the watched workbook and the calendar and mail
   pipelines; reuse them rather than adding a new one.
4. The dashboard payload for the card face: a workbook plugin that asked for a
   big number does not render the classic tracker face.
5. The existing frontend test stack for the dialog: it opens with a connection,
   does not open without one, shows the quiet line instead, and states that the
   fields were filled in.

Prior art in this repository: the wizard server and core suites; the runner and
runtime suites for a plugin card's states; the dashboard payload tests; the
marketplace SPA suites for a dialog's focus, Escape, and copy.

## Out of Scope

- Compare and aggregate sources in the wizard. Each needs two sources; the
  registry keeps authoring them. Desk state is out for the same reason: the
  plugin runtime is not handed the host callbacks that source reads.
- Editing a plugin's answers after install. The manager deletes and rebuilds, or
  uses the existing instance setup for a workbook.
- Sub-minute refresh, and any scheduling that survives more than one process.
- Turning an existing installed plugin's stored schedule on. Plugins installed
  before this spec keep their behaviour until rebuilt.
- A no-JavaScript equivalent of the skeleton dialog. The no-script path keeps
  the question walk, unchanged.
- Any change to what a plugin may read, reach, or write. The vocabulary is
  closed and the composer, not the model, decides permissions.

## Further Notes

The refusal the wizard produces today for a mail ask is the clearest symptom of
the underlying problem: the vocabulary is wide and the wizard uses one corner of
it. The mail narrowing is therefore part of this spec, not a follow-up.

The four vocabulary sets are the artifact to get right. They are the contract
between the questions, the autofill, and the composer; if a label is not in the
set, no surface can offer it and no model can introduce it. The sets live in
one module, and the tests pin them to the host's own binding list, so a look
that names a binding no reader fills fails before it can ship.

The ticket set did not include a ninth ticket for the card face or the manual
number: both landed inside 02 and 06, because a tile that shows the wrong face
or offers no way to set its number is a broken tile, not a follow-up.

