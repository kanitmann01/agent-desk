# 02: What the tile shows, and how it looks

**What to build:** after choosing a source, the manager chooses what the tile shows (the latest figure, how it moved, whether it is on track, the rows behind it, the items that need them, or one status line), then how it looks (big number, colored status, up-or-down, short trend, bar to a target, table, list, timeline, checklist). Only the combinations that source can actually fill are offered, and a question with one legal answer is skipped rather than asked.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Each source offers only the shows its reader binds; a figure source never offers "the items that need me".
- [ ] Each show offers only the manners that fit it; a trend is offered only when the source binds a point series.
- [ ] The installed ui-schema contains exactly the chosen element and binding.
- [ ] A workbook instance renders the face the ui-schema asks for, and the classic tracker face remains available as one of the manners.
- [ ] The preview names the chosen show and look before approval.
