# 03: When the tile updates

**What to build:** the wizard asks when the tile should update, offering when the desk is opened, a named clock time, and when the watched thing changes. The choice is written into the installed plugin and named in plain words in the preview. A source with no event to watch is never offered the change option.

**Blocked by:** 01, 02.

**Status:** ready-for-agent

- [ ] The update question offers opened, morning, hourly, Monday morning, and Friday afternoon, plus when it changes where an event exists.
- [ ] The web page and the desk fact offer no change option.
- [ ] The installed plugin carries the chosen activation events: one widget event plus one schedule event or one hook event.
- [ ] The preview names the chosen update mode in the same words the manager chose.
