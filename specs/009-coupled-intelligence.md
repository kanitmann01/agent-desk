# 009 — Coupled intelligence

Status: ready-for-agent
Owner: lead
Date: 2026-11-18

## Problem Statement

The desk reports what happened and never says what it means for this person.
A user who hand-picks workbook rows gets arithmetic and no sentence about the
relationship those rows reveal. The Outlook brief names the top email but never
composes a reply, and never nags about the thread that has been waiting three
days. The calendar knows the next meeting but not what to read before it. The
research card answers one question and forgets it by the next one. Meanwhile the
memory bank — the only place that knows the user's projects, people and habits —
is wired into the assistant chat alone, so no card can use it, and nothing in the
product stores a preference at all: a preference today is an untyped fact the
user never agreed to and cannot edit.

## Solution

One host-side insight pass over the dashboard's card payloads. Every card that
already carries structured data gets a short, deterministic reading of it,
written in the user's own frame: what the numbers show, which rows are worth
selecting, which chart fits, which threads are quietly waiting, what to read
before the 10:30. A typed preferences store (chart shape, reply tone and length,
focus topics, prep window, how talkative the cards are) is edited by the user in
Settings and honoured by every reading. Memory is consulted where a card has a
subject to ask about, and only through the approval-gated bank that already
exists.

Model calls happen only when the user presses a control — "Draft this reply",
"Tighten this reading" — with the panel-disclosed payload the workbook
suggestion flow already established. Nothing infers a preference, nothing
silently spends a request, and every reading that could not be computed says so
in one line rather than inventing a number.

## User Stories

1. As a workbook user, I want the rows I selected turned into candidate relationships ("EMEA is 62% of Booked, and the ratio has held for six months"), so that selection means something beyond a sum.
2. As a workbook user, I want the host to name the numeric column that actually varies, so that I am not charting a constant.
3. As a workbook user, I want a chart shape recommended from the relationship found (trend → line, share → bar, ratio → table), so that I stop guessing between bar and line.
4. As a workbook user, I want the chart recommendation to explain itself in one clause, so that I can disagree with it.
5. As a workbook user, I want outlier rows called out by name, so that the anomaly is a sentence and not a chart-reading exercise.
6. As a workbook user, I want the desk to propose which rows to select in the first place, so that I start from a defensible subset instead of "all rows".
7. As a workbook user, I want correlation claims only when the sample is big enough and the coefficient is strong, so that I never see a fabricated pattern.
8. As a workbook user, I want one line when the table is too small or too flat to say anything, so that silence is never mistaken for analysis.
9. As an Outlook user, I want the threads that have waited on me the longest named first, so that neglect becomes visible before it becomes a complaint.
10. As an Outlook user, I want a reminder that explains why a thread is waiting (question asked, no reply sent, N days old), so that the nag is auditable.
11. As an Outlook user, I want a reply skeleton drawn from the thread's own subject and greeting, so that I start from my house style instead of an empty box.
12. As an Outlook user, I want "Draft this reply" to use my tone and length preferences, so that the draft sounds like me.
13. As an Outlook user, I want the exact payload disclosed before any draft is composed, so that I know what left my machine.
14. As an Outlook user, I want the draft to open in the reply writer rather than be sent, so that I stay the author.
15. As a calendar user, I want three research prompts aimed at the next meeting, so that prep starts from a question instead of a blank page.
16. As a calendar user, I want those prompts to use the meeting's own title, attendees and time, so that they are about this meeting.
17. As a calendar user, I want the prompts bounded by my prep window, so that I am not handed an hour of reading before a 15-minute sync.
18. As a calendar user, I want the prompts to become research questions with one press, so that prep and research are one loop.
19. As a research user, I want the next questions derived from the last answer's own entities, so that research continues instead of restarting.
20. As a research user, I want my focus topics to steer what is suggested, so that the desk follows my agenda, not its own.
21. As a user, I want to set chart preference, reply tone, reply length, focus topics and card verbosity once, in Settings, so that every card reflects them.
22. As a user, I want preferences stored as typed, validated values rather than free text, so that a typo cannot silently disable a feature.
23. As a user, I want my preference edits to take effect on the next dashboard read, so that I can see the change immediately.
24. As a user, I want an invalid preference rejected with a named reason, so that I know what to fix.
25. As a user, I want cards to consult my memory for the subject they are about, so that what the desk already knows shows up where it is relevant.
26. As a user, I want memory lines to be attributed ("from your notes"), so that I can tell memory from arithmetic.
27. As a user, I want the cards to work — with an honest note — when the memory bank is locked or empty, so that security never becomes a blank screen.
28. As a user, I want no memory write on any of these paths, so that reading a card can never change what the desk believes.
29. As a user, I want a quiet/normal/chatty control over how much the cards say, so that insight does not become noise.
30. As an operator, I want every insight failure to degrade to an empty insight block plus a note, so that a plugin card is never broken by the intelligence layer.
31. As an operator, I want the insight pass to stay off the network unless pressed, so that dashboard polling costs nothing.
32. As a reviewer, I want the derived elements to reuse the ten whitelisted element kinds, so that no plugin manifest or SPA build is needed to ship a reading.

## Implementation Decisions

- A new host package owns coupled intelligence: a preferences store, pure table
  maths, four per-plugin derivations, and one service entry point. Plugins stay
  declarative and unchanged; nothing in a manifest learns about insight.
- The single seam is the dashboard payload assembly, which already holds the
  plugins, the memory store, the calendar bridge, the mail store, the settings
  store and the audit connection. The insight pass runs there, once per card,
  and is the only place the four families are dispatched.
- Derivations return host elements drawn from the existing ten whitelisted
  kinds (text, checklist, status, list). The SPA already renders any element in
  a card payload, so no SPA change, no rebuild and no manifest change is needed.
  A card's payload gains an additive "insight" object (source, preferences used,
  optional press control, optional honest note) beside the appended elements.
- The tracker reading must expose the bounded table it already parses
  (headers, and up to 60 rows by 10 columns) so the insight pass can reason over
  the same cells the aggregate came from, without reopening the file and without
  shipping the whole sheet to the browser.
- Preference schema, version 1, as one JSON document in the data dir:
  chart (auto|bar|line|table), replyTone (direct|warm|formal), replyLength
  (one-line|short|paragraph), insightDensity (quiet|normal|chatty),
  focusTopics (list of up to 10 short strings), prepMinutes (0-120).
  Reads merge defaults; writes validate the whole document and reject unknown
  keys with a named code, so a typo never becomes a silent no-op.
- Table maths is pure and conservative: correlation needs at least 8 paired
  points and |r| >= 0.6; trend needs at least 6 dated points and a monotonic
  fraction >= 0.7; share needs at least 3 groups and a top group >= 50%; an
  outlier needs at least 8 points and |z| >= 2.5; a ratio needs at least 5 rows
  with a max/min <= 1.5. Each statement carries the numbers that justify it.
- Two HTTP endpoints are added: read/replace preferences, and one press
  endpoint that composes a reply draft. The press endpoint is refused with the
  same conflict code the other endpoint-gated features use when the model path
  is off, and it discloses the exact payload it would send before sending it.
- No path on this feature writes memory. Recall is read-only, wrapped so that a
  sealed, absent or empty bank yields a note rather than an exception.
- Density drives nothing but length: quiet keeps one line, normal keeps the
  three-item reading, chatty adds the checklist of suggested rows/topics.
- Determinism: every derivation takes an injected clock and injected prefs, so
  tests never depend on wall time.

## Testing Decisions

Good tests here assert what a user or an operator can observe: the shape of a
card payload, the sentences a reading carries, the HTTP status and body of the
two endpoints, and the note a degraded reading shows. They do not assert private
helper names, ordering of internal dicts, or the presence of a particular module.

- The single seam is tested once, at the dashboard payload: given a server with
  cards, the payload carries insight for each family, and a raising derivation
  degrades to an empty insight block without breaking the card. Prior art:
  the plugins-execute and dashboard tests, which build a server through the
  existing harness and assert on payload shape.
- Preferences are tested through their endpoint as well as their store: valid
  write round-trips, unknown key and bad vocabulary are refused with a code, and
  the defaults are what a fresh data dir reports.
- Table maths is tested as pure functions over hand-built tables, including the
  refusals (too few rows, flat column, no variance) because the refusals are the
  product promise against fabricated patterns.
- The press endpoint is tested with an injected completer that records what it
  received: the disclosure line is present, the payload is bounded, and the
  refusal path is a conflict when the model path is off.

## Out of Scope

- Any scheduled or background model call, any automatic memory write, and any
  learning of preferences from behaviour.
- SPA changes: the readings use element kinds the SPA already renders.
- Cross-plugin insight (one card reasoning about another card's data).
- The twenty-idea catalogue beyond recording it as scored candidates.
- Real Outlook send/reply: the draft lands in the existing reply writer only.

## Further Notes

- The five behaviours the user named map to four tickets: workbook
  relationships/chart/rows, digest reply reminders and semi-draft, and
  calendar pre-meeting research topics, with research next-question as the
  fourth derivation and memory coupling as the fifth ticket.
- The catalogue of twenty further ideas lives beside this spec and is scored so
  the next round can pick from it without re-deriving the analysis.
- The honest gap: the digests remain header-only (.eml metadata), so a reply
  draft can never quote the message body; the draft is a skeleton plus the
  user's tone, and the card says so.
