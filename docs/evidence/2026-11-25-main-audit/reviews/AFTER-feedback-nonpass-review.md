FINDINGS

Photographs reviewed: 15 of 15. Worktree: `D:/20-projects/Personal Agents/.worktrees/audit-after-main-b396694` at `b39669491b965ef6c6624903db30e0b9df552004`.

## dashboard-research

- Photographs: `dashboard-research-early.png` shows the Asking your AI button and sourced-summary placeholder; `dashboard-research-late.png` shows the same wait with the longer-than-usual line; `dashboard-research-result.png` shows the mock answer and a grey Research button beside the now-empty question field.
- Cause: `_is_idle` requires the control not to be disabled (`tools/feedback_walkthrough.py:382-387`), while a successful ask clears the field and the command bar correctly disables Research for empty input (`frontend/src/components/CommandBar.tsx:121-125,170`), so the result has `busy=false`, `pending=false`, and `ok=true` but `idle=false`; the 11-second late photograph is expected to be busy with a 12-second mock, and the result poll returned the answer rather than timing out (`tools/feedback_walkthrough.py:542-555,622-648`). `after-feedback-timing.txt` records only the 144-second whole-command span, not a per-action timeout.
- Busy question: neither explanation applies. The control did clear, and the run did not give up before 12 seconds; the instrument mislabels the correct empty-input disabled state as still busy.
- Class: instrument limitation.
- Fix: change the result verdict to require `not result.busy` instead of `result.idle`.
- Severity: N/A, instrument only.

## dashboard-reply

- Photographs: this action has no photographs because it was absent before a click; the dashboard photographs show the tracker's Explain this range control and the Research control, but no Draft a reply control.
- Cause: the action searches card buttons for `Draft (a|the) reply` and returns absent immediately when none matches (`tools/feedback_walkthrough.py:203-213,290-310,602-608`), while the full seed installs only `competitor-watch`, `excel-report`, and `presentation-starter` and does not enable mail or install a digest card carrying a reply-draft press (`tools/layout_audit.py:2396-2449`; `registry/index.json:2-70`), although `PluginCardView` does render such a press when present (`frontend/src/dashboard/PluginCardView.tsx:485-487`). The command log has no mock call for this action, and the timing record has only the 144-second whole-command span.
- Class: instrument limitation, missing eligible fixture data rather than a missing product feature.
- Fix: seed or install one digest card whose `insight.press.kind` is `reply-draft` before locating the action.
- Ticket: none in spec 030 or spec 031; issue 329 only migrates the existing reply-draft wait to the shared primitives.
- Severity: N/A, instrument only.

## inbox-draft

- Photographs: none. The action returned absent before a click, so the run produced no Inbox waiting-card early, late, or result photograph.
- Cause: the action searches `article.widget` controls for `Draft (a|the) reply` (`tools/feedback_walkthrough.py:257-268`), but Inbox cards render their primary action, Dismiss, Save draft, Snooze, and Ask for more info (`src/agentdesk/server/inbox_view.py:36-126`), and mail follow-up cards use Handled (`src/agentdesk/mail/watcher.py:245-280`); the built model-backed flow drafts on a dashboard reading and stages the result as an Inbox card (`specs/010-acting-on-the-reading.md:30-43`), so no waiting card offers the requested model-backed draft. The command log has no mock call for this action, and the timing record has no action-specific wait.
- Class: feature not built yet.
- Ticket: none of issues 329 to 344 covers adding a model-backed reply-draft action to Inbox waiting cards; issue 329 covers the existing dashboard draft wait only.
- Fix: file a new ticket for the Inbox waiting-card draft action, or remove this action from the seven-action acceptance if the intended flow remains dashboard to Inbox.
- Severity: N/A, unbuilt feature.

## Met actions

- `dashboard-explain`: `dashboard-explain-early.png` shows Explaining this range with a dashed placeholder, `dashboard-explain-late.png` adds the longer-than-usual line, and `dashboard-explain-result.png` shows the model sentence and Source: model.
- `assistant-ask`: `assistant-ask-early.png` shows Asking with a thread placeholder, `assistant-ask-late.png` adds the longer-than-usual line, and `assistant-ask-result.png` shows the user's question, the Assistant mock answer, and an enabled Ask button.
- `agents-presentation`: `agents-presentation-early.png` shows Building with a deck placeholder, `agents-presentation-late.png` adds the longer-than-usual line, and `agents-presentation-result.png` shows the completed presentation receipt, sources, template, Download .pptx, and feedback form.
- `wizard-describe`: `wizard-describe-early.png` shows Working with a card-and-chart placeholder, `wizard-describe-late.png` adds the longer-than-usual line, and `wizard-describe-result.png` shows the echoed request, data-source choices, and an enabled Ask button.
