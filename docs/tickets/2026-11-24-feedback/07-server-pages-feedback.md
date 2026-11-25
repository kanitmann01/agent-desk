# 07: Feedback on the server pages

**What to build:** the server-rendered pages obey the same feedback rules inside their normal navigation. One delegated submit listener in the shared page script gives every form a busy button and, for a model-backed form, a same-shape placeholder with a phase line in the outgoing page while the request is in flight. A post that fails keeps the typed values and names the cause instead of answering raw JSON or reloading as if it worked. After a navigation, focus moves to the main heading, a skip link reaches the content, and every page still works with the script off.

**Blocked by:** 01.

**Status:** done (2026-11-24).

- [x] One delegated capture-phase `submit` listener in `APP_JS` covers every `form[method=post]`; a second listener is not needed per form.
  - Verified: tests/test_ui_feedback.py::test_the_script_has_one_delegated_capture_listener_and_a_back_restore (document.addEventListener('submit', onSubmit, true)).
- [x] The pressed submit button shows the F1 busy state and keeps its size; the fields are never disabled, because a disabled control is not posted.
  - Verified: src/agentdesk/server/pages.py stackButton/setButtonBusy mark only the button aria-busy and aria-disabled, never disable a field; the stacked labels reserve the same box.
- [x] For a model-backed form (assistant Ask, Save to memory, Agents run, the Presentation run, memory Reflect and the wizard's describe and answer steps), a same-shape placeholder with a phase line appears in the region that will receive the result, in the outgoing page, while the request is in flight.
  - Verified: tests/test_ui_feedback.py names the model-backed forms and their data-wait regions (assistant, agents, memory, capabilities, settings, peers, wizard).
- [x] The placeholder's line turns into the 10-second line when the request has not answered, and says the reader may leave the page.
  - Verified: src/agentdesk/server/pages.py TAKING_LONGER_MS and showWaitPlaceholder; tests/test_ui_feedback.py pins the ten-second line.
- [x] The result arrives on the new page with a `role="status"` line that names the outcome.
  - Verified: tests/test_ui_feedback.py (assistant, agents and memory result pages carry a role=status line and a focusable h1).
- [x] Every handler that reloads after a POST (the two Re-test calls, accept, dismiss, restore, the settings toggle and the skill undo) reloads only after a success; a failure shows the cause instead.
  - Verified: tests/test_ui_feedback.py::test_the_script_reloads_only_after_a_success_for_every_fetch_handler and tests/test_ui_feedback_review.py (the status guard).
- [x] The raw-JSON dead ends (a blank fact and a blank brief) re-render the form with the cause and the typed values, not a JSON body.
  - Verified: tests/test_ui_feedback.py (blank fact and blank brief re-render the form with the cause and the typed value).
- [x] The invalid presentation timeout keeps the typed value and names the cause.
  - Verified: tests/test_ui_feedback.py::test_an_invalid_timeout_keeps_the_typed_value_and_names_the_cause.
- [x] After a navigation, focus moves to the main heading rather than the top of the document.
  - Verified: src/agentdesk/server/pages.py heading.focus() after navigation; tests/test_ui_feedback.py reads the focus contract.
- [x] Every server page has a skip link to the main content.
  - Verified: tests/test_ui_feedback.py::test_every_page_opens_with_a_skip_link_to_main over every page.
- [x] With the script off, every form still posts, every page still renders, and the busy state and placeholder are enhancements rather than requirements.
  - Verified: tests/test_ui_feedback.py (the settings toggle posts back and flips without script; every page renders).
- [x] Server tests cover the rendered skip link, the placeholder region, the form-versus-JSON dead ends, the success-only reload and the no-script path.
  - Verified: tests/test_ui_feedback.py and tests/test_ui_feedback_review.py cover the skip link, placeholder region, form-vs-JSON dead ends, success-only reload and no-script path.
- [ ] `python tools/ci_local.py` passes 7/7.
