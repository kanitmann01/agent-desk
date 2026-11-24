# 04: A scheduled tile refreshes on its own

**What to build:** a tile set to a clock time serves its last reading and refreshes when the clock comes due, without being re-read every time the home screen is opened. The install takes one reading so the tile is not blank until the first tick.

**Blocked by:** 03.

**Status:** ready-for-agent

- [ ] Opening the home screen does not re-read a scheduled tile; the tile shows the stored reading and its as-of time.
- [ ] The minute tick refreshes a scheduled tile once its time has passed, and not before.
- [ ] A newly installed scheduled tile shows one reading immediately.
- [ ] Re-testing a scheduled tile reads once, on demand.
