# 07: Feedback on the server pages

**What to build:** the server-rendered pages obey the same feedback rules inside their normal navigation. One delegated submit listener in the shared page script gives every form a busy button and, for a model-backed form, a same-shape placeholder with a phase line in the outgoing page while the request is in flight. A post that fails keeps the typed values and names the cause instead of answering raw JSON or reloading as if it worked. After a navigation, focus moves to the main heading, a skip link reaches the content, and every page still works with the script off.

**Blocked by:** 01.

**Status:** queued.

- [ ] One delegated capture-phase `submit` listener in `APP_JS` covers every `form[method=post]`; a second listener is not needed per form.
- [ ] The pressed submit button shows the F1 busy state and keeps its size; the fields are never disabled, because a disabled control is not posted.
- [ ] For a model-backed form (assistant Ask, Save to memory, Agents run, the Presentation run, memory Reflect and the wizard's describe and answer steps), a same-shape placeholder with a phase line appears in the region that will receive the result, in the outgoing page, while the request is in flight.
- [ ] The placeholder's line turns into the 10-second line when the request has not answered, and says the reader may leave the page.
- [ ] The result arrives on the new page with a `role="status"` line that names the outcome.
- [ ] Every handler that reloads after a POST (the two Re-test calls, accept, dismiss, restore, the settings toggle and the skill undo) reloads only after a success; a failure shows the cause instead.
- [ ] The raw-JSON dead ends (a blank fact and a blank brief) re-render the form with the cause and the typed values, not a JSON body.
- [ ] The invalid presentation timeout keeps the typed value and names the cause.
- [ ] After a navigation, focus moves to the main heading rather than the top of the document.
- [ ] Every server page has a skip link to the main content.
- [ ] With the script off, every form still posts, every page still renders, and the busy state and placeholder are enhancements rather than requirements.
- [ ] Server tests cover the rendered skip link, the placeholder region, the form-versus-JSON dead ends, the success-only reload and the no-script path.
- [ ] `python tools/ci_local.py` passes 7/7.
