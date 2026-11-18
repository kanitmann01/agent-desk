# 010: The desk acts on what it read

**Status:** done (2026-11-18); evidence in `docs/evidence/2026-11-18-acting-on-the-reading.md`
**GitHub:** issue #136; its six tickets are #137–#142
**Builds on:** spec 009 (the coupled reading), branch `feature/coupled-intelligence`

## Problem Statement

Spec 009 made every dashboard card say something about itself: the workbook
names the relationship in the rows the user picked, the calendar sizes prep to
the time they have, the digest names the thread that matters and offers a
skeleton, the research card proposes the next questions. Two things stop that
from being useful.

First, the readings are inert. A reading can carry a *press* — an offer to
explain a finding, or to draft a reply — but no surface draws the control that
presses it. The JSON route answers when called by hand; on the screen, the user
sees prose and nothing to do with it.

Second, the readings are opaque about themselves. A card states a finding
without saying which of the six preferences shaped it, or whether it read
memory, the calendar, or only the card's own rows. A user who edits `replyTone`
or `chart` cannot tell whether anything changed, and a user who distrusts the
coupling cannot see that no message body was opened.

There is a third, narrower gap: in a built SPA the workbook card draws its own
figure and ignores the elements the reading appends, so on that surface the
best feature in the branch is invisible.

## Solution

Make the press real on both surfaces, and make every reading say what it used.

A press becomes a control on the card. On the server-rendered dashboard it is a
plain form — the page has no client script, and this branch will not add one —
that posts the offer to a page which either shows the explanation or stages the
drafted reply as an inbox card. In the SPA it is a button beside the reading
that calls the JSON route and renders the answer in place.

A drafted reply never sends. It is resolved to the thread it belongs to, staged
as a suggestion card through the same seam a hand-typed reply already uses, and
accepted by the user like any other card — which is what writes the `.eml` to
the outbox. A model draft is labelled as one.

Every reading gains receipts: which preference keys changed its output, and
which inputs it consulted (the card's own rows, memory, the calendar). They
travel in the payload and are printed as one quiet line under the reading. A
reading that used nothing says so, which is the most useful state of all.

## User Stories

1. As a user looking at a workbook reading, I want a button under it that explains the finding, so that a number I do not understand becomes a sentence I do.
2. As a user pressing that button, I want to see what will be sent and what will not before anything is sent, so that the coupling never surprises me.
3. As a user with the model path off, I want the button to tell me that rather than to fail silently, so that I know the desk is deterministic rather than broken.
4. As a user reading a digest, I want a button that drafts a reply in my tone, so that the blank page is gone but the words are still mine.
5. As a user who presses "Draft a reply", I want the draft to arrive as a card I can edit and accept, so that nothing leaves the desk without my hand.
6. As a user who accepts that card, I want the existing outbox write to happen exactly as it does for a reply I typed, so that one code path owns sending.
7. As a user whose mail folder is off or whose thread cannot be identified, I want a named refusal that says which, so that I can fix the cause.
8. As a user whose thread subject matches two messages, I want the desk to refuse rather than guess, so that a draft never lands on the wrong thread.
9. As a user editing `replyTone`, I want the card to show that the tone shaped this reading, so that I can see my preference at work.
10. As a user who has changed nothing, I want a reading to say it used the defaults, so that I am not shown a receipt for a preference I never set.
11. As a user who wonders whether memory was read, I want the card to name its inputs, so that the privacy claim in Settings is visible where it matters.
12. As a user with a sealed memory bank, I want the receipt to say memory was not consulted rather than omit it, so that silence is never mistaken for "nothing found".
13. As a user on the server-rendered dashboard, I want every one of these controls to work without JavaScript, so that the page keeps its promise.
14. As a user on the SPA, I want the workbook card to show the same reading the server shows, so that the two surfaces do not disagree.
15. As a user who presses a button twice, I want the second press to be idempotent in effect, so that I do not get two inbox cards for one draft.
16. As an operator reading the audit log, I want a press and a staged draft recorded, so that automated composition is auditable.
17. As a developer adding a seventh reading, I want receipts to be part of the reading contract rather than something each card invents, so that the surface draws them once.
18. As a developer, I want the press page and the JSON route to share one composer, so that the two surfaces cannot drift.

## Implementation Decisions

- **Receipts belong to the reading.** The reading type gains two tuples: the preference keys whose non-default value changed the output, and the input names it consulted. The service writes them next to the existing status and press fields. A family that used nothing returns empty tuples and the card prints "Used the defaults; read only this card."
- **Receipt naming is a fixed vocabulary**, so the surface can print it without a lookup: `rows`, `memory`, `calendar`, `preferences`. Preference receipts carry the key, not the value.
- **The press stays data, the button is markup.** The payload keeps the offer as it is today; the renderers decide how to draw it. No press text is ever printed as raw HTML.
- **One composer, two callers.** The existing draft route and the new press page call the same function; the page renders what the route returns. Nothing in the page composes its own draft.
- **A drafted reply is staged, not sent.** Staging reuses the inbox suggestion path a hand-typed reply uses, with `draft` set to the composed text and meta recording the resolved thread; acceptance still runs the single outbox writer. A staged draft is labelled with its source (`model` or `template`) in the card's own copy.
- **Thread resolution is exact and refuses ambiguity.** The draft request carries the thread's subject and sender, which the digest reading already has; the server resolves them against the mail view, and answers with a named refusal when mail is off (no watcher), nothing matches, or more than one message matches. No message id is added to any payload.
- **The server-rendered press is a form, posted to a page.** Hidden fields carry the offer (kind, finding text, subject, sender, plugin id); the handler answers with a small page that shows the explanation, or the draft with the existing stage form. No inline script, no new client code.
- **Repeated presses do not accumulate cards.** A second identical press for the same thread and the same text reuses nothing new: the page says the draft is already staged and links the existing card.
- **The SPA draws what the server draws.** The workbook card gains the same element mapping the generic card uses, and both surfaces print the receipt line from the same payload field.
- **Preference receipts name keys, not values**, so a receipt cannot leak a topic list into a shared screenshot.

## Testing Decisions

Test external behaviour only, at the highest existing seam.

- **The seam suite** proves receipts travel: a reading that declares keys and inputs produces `payload.insight.receipts`, a reading that declares nothing produces empty tuples, and an unreadable preference file still yields a receipt that says defaults.
- **The press suite** proves refusals and staging over HTTP with an injected composer: model off answers 409 with the disclosure; a subject matching no message answers 404 naming the subject; a subject matching two answers 409 naming both senders; a successful press stages exactly one suggestion card whose draft is the model text and whose meta names the thread; accepting that card writes the outbox file, and pressing again stages nothing new.
- **The HTML surface suite** proves the form exists on a card that carries a press and is absent on one that does not, that hidden values are escaped, and that the press page prints the answer with the stage form.
- **Prior art to follow:** `tests/test_insight_press.py` (press refusals), `tests/test_server_insight_html.py` (element rendering and escaping), `tests/test_server_preferences_form.py` (a no-JS form posting to a handler with a redirect), `tests/test_mail_reply.py`-style outbox assertions, and `frontend/src/test/tracker-setup.test.tsx` for the SPA card.
- **The frontend half needs `npm ci`**; `frontend/node_modules` is empty in this checkout, so those two tickets declare it rather than pretending a green run.

## Out of Scope

- The commitments ledger (idea 1) and the other eighteen ideas in `docs/ideas/2026-11-18-coupled-intelligence.md`. This spec finishes the coupling it starts from; it does not add a new asset.
- Any change to what the readings say. Their sentences, thresholds and families are spec 009 and stay as shipped.
- Learned preferences, implicit inference, and any write to memory. Receipts make the coupling legible; they do not widen it.
- Sending mail, scheduling, or any new outbound path.
- The registry content-pin drift that fails 13 tests at base; it is recorded in ticket 06 of spec 009.

## Further Notes

- The press is the shortest path from "the desk noticed" to "the desk did". It is also the first place where a model's words would enter a durable artefact, which is why staging goes through the approval card rather than the outbox.
- Receipts are cheap now and expensive later: every family already knows which preference it consulted, but reconstructing that from sentences would be guesswork.
- The two SPA tickets were written as unverifiable when dependencies were absent. They were verified after `npm ci --include=dev`: `tsc --noEmit` exit 0 and 24 vitest files / 272 tests green (with `NODE_ENV=test`; this machine exports `production`, which breaks every render test).
- Both remaining gate failures are the pre-existing registry content-pin drift, reproduced identically at base. The gate's own `--plugins` flag is appended once per plugin and argparse keeps only the last, so it checks one plugin; that is a separate defect.
