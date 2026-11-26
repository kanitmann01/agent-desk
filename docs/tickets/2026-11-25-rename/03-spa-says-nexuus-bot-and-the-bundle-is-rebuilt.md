# 03: The SPA says Nexuus Bot, and the committed bundle is rebuilt

**What to build:** the single-page app and the bundle a browser actually downloads say Nexuus Bot. The source and shipped tab titles, both rail wordmarks, the avatar title and its initials, the session-expired copy, the update banner, and the frontend prompts and sentences that name the product read `Nexuus Bot`, and the avatar initials read `NB`. The agent face already carries the name; product and agent are one name now, so the wordmark beside the face and the face tooltips agree. The committed bundle is rebuilt once from the new source and committed; a second production build changes nothing, and the hosted workflow finds no committed-bundle diff. The guard's SPA-family entries leave the temporary list in the same change.

**Blocked by:** 01b: The guard that reads it.

**Status:** ready-for-agent

- [ ] The source tab title, the shipped tab title in the committed bundle, both rail wordmarks, the avatar title and its initials, the session-expired copy, the update banner, and every frontend prompt or sentence that names the product read from one approved frontend constant and say `Nexuus Bot`, with initials exactly `NB`. The frontend tests assert it (prior art: `frontend/src/test/shell.test.tsx`, `frontend/src/test/face-rail.test.tsx`, `frontend/src/test/brief-decisions.test.tsx`), and each updated expectation fails against today's copy before the change.
- [ ] The wordmark beside the face and the face tooltips use the same name; the tests that pinned two different names now pin one.
- [ ] The committed SPA is rebuilt once and committed. A second production build is byte for byte identical, and the hosted workflow reports no committed-bundle diff.
- [ ] Browser storage keys, the session cookie and the existing theme event are unchanged, and their tests stay green.
- [ ] The before-and-after count for the family comes from the guard's count report: old display occurrences in the family's files are zero after the change, and both counts are recorded on the pull request.
- [ ] The SPA family's entries are removed from that family's file of the guard's temporary list in this change, and only from that file; the guard stays green at every point.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS`.
- [ ] No test in this ticket starts a real desk, a walk or the application, and no walk is run; the rebuild is a production build command, not a run of the application.
