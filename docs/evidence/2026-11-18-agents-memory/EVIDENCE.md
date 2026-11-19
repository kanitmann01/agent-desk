# Evidence: memory-aware agents, end to end (2026-11-18)

Spec 012 (issue #167), branch `feat/agents-memory`. This file records the
browser walkthrough that proves the layer works end to end: an agent run
recalls nothing, feedback becomes a reviewed fact, and the next run recalls
it and shows it in its artifact.

## The honest disclosure first

The model in this walkthrough is `tools/mock_endpoint.py`, the local
OpenAI-compatible stand-in shipped with this branch, not a real model and
not a real key. It was configured through the ordinary settings page like
any bring-your-own-key endpoint. Everything else in the screenshots is the
real system: the routes, the memory store, hybrid recall, the capture
loop, the review card, acceptance, entity linking, the provenance graph.
The mock's one job is to make the recall visible: it echoes the known-facts
lines the host injected into the prompt back into its reply, so a run that
recalled a fact carries a "Grounded in your known facts" slide one would
not otherwise see from canned words.

## Environment

- App: the branch's server, booted on 127.0.0.1:8791 over a fresh
  temporary data dir (no sample data, empty memory).
- Endpoint: `python tools/mock_endpoint.py --port 8788`, saved in Settings
  as `http://127.0.0.1:8788/v1` (screenshot 02 shows the CONFIGURED card).
- Browser: ZCode's in-app browser, driven through the walkthrough below.

## The walkthrough

1. **The surface is reachable.** The dashboard rail carries an Agents
   entry beside Assistant (ticket #172, rebuilt bundle). Screenshot 01.
2. **BYOK configured.** Settings, Endpoint: base URL of the mock, key
   saved, page shows CONFIGURED. Screenshot 02.
3. **First run, honest empty receipt.** On `/agents`, the Presentation
   agent ran with the brief "Q3 business review for my manager Dana".
   The run recorded: status ok, artifact = slide outline, receipt
   "This run used nothing from memory." (memory was empty; silence is
   the designed empty). Screenshot 03.
4. **Feedback given.** The run's "How did it land?" form was posted with
   "My manager Dana liked it and wants concise slides with fewer
   bullets." The run page now shows the feedback with its timestamp.
5. **Capture staged a review card.** The inbox showed "Fact from
   Agents: Dana", origin "Captured from your Agents activity by the
   company endpoint", draft = the feedback sentence. Screenshot 04.
   (The extraction itself also went through the endpoint: the mock
   returned the user's own words as the candidate, with Dana as a
   person entity.)
6. **Acceptance stored the fact.** "Save to memory" was pressed; the
   inbox emptied. Nothing was stored before that press.
7. **Second run recalled it.** The Presentation agent ran again with
   "Q4 kickoff presentation for Dana, keep it tight". The run recorded
   the receipt "This run used these facts from memory:" listing the
   stored fact, and the artifact gained the closing slide "Grounded in
   your known facts" carrying it. Screenshot 05 (run 1 below it still
   says it used nothing: the two receipts sit side by side in history).
8. **The layer is generic.** The Worksheet brief agent, added as a
   registry entry only (no runner, route or memory change; ticket
   #171), ran with "what should I know about the sales workbook for
   Dana": same recall, receipt listing the fact, outline artifact
   grounded in it. Screenshot 06.
9. **Memory tells the same story.** The memory page shows the Agents
   capture switch (on, beside Assistant/Research/Workbook tracker),
   the stored fact with origin "Agents, You approved", the Dana
   entity chip, and the provenance graph: writer "Captured from
   Agents", the retained run excerpt, the world fact. Screenshot 07.

## Files

- `01-dashboard-rail-agents.png`
- `02-settings-endpoint-configured.png`
- `03-first-run-used-nothing.png`
- `04-inbox-review-card.png`
- `05-second-run-recalled-the-fact.png`
- `06-worksheet-brief-agent.png`
- `07-memory-page-fact-and-origin.png`

## Reproducing

```
python tools/mock_endpoint.py --port 8788     # terminal 1
python -m agentdesk.server                     # terminal 2, fresh data dir
# open the printed auth URL, then:
# Settings -> Endpoint -> http://127.0.0.1:8788/v1 + any key -> Save
# /agents -> run Presentation -> feedback -> /inbox accept -> run again
```
