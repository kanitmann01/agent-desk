Evidence for ticket #229 (workstream 9, nudges budget, of spec 017 / #217).

Every capture ran on a real server on a real socket (python -m agentdesk.server)
with a fresh temp AGENTDESK_DATA, the mock endpoint (tools/mock_endpoint.py)
standing in for the company LLM, and curl through the loopback. No test
harness, no direct call to POST /inbox/consolidate anywhere.

- repetition-detector-from-normal-use.txt: 9a. Five similar asks go
  through the real research surface; the first ordinary read proposes
  the skill card. The detector rides the inbox's catch-up-on-read hook.
- dismissed-shelf-purge.txt: 9f. A dismissed card is listed on the shelf
  inside its window; aged 45 days past dismissal and read again, the
  shelf prunes it instead of listing a restore button that answers gone.

The other items of the workstream are code-and-test fixes without a new
user-visible page state; their proofs live in the suite:

- 9b: tests/test_briefs.py::test_accepting_a_brief_prevents_the_twin
- 9c: tests/test_server_inbox_api.py::test_a_string_window_hours_is_refused_at_the_boundary
- 9d: tests/test_server_inbox_api.py::test_concurrent_spends_cannot_overspend_the_day
- 9e: tests/test_repetition.py::test_undo_starts_the_cooldown_so_consolidation_does_not_repropose
- quiet-hours pins: tests/test_server_inbox_api.py::test_quiet_hour_boundaries_are_pinned
  and test_notified_today_rolls_over_at_local_midnight

Each of those tests fails on the code before its fix (verified by
reverting src/agentdesk and running the six new tests: 6 failed).
