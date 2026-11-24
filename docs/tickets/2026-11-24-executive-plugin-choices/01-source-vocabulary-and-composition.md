# 01: A plugin for any source, not just the workbook

**What to build:** a manager describing a plugin can choose what it watches from every source the desk can read, and the installed plugin reads that source. Describing "a morning list of my mail" and choosing My mail installs a mail plugin whose tile shows its items, instead of a workbook tracker. The wizard no longer builds anything until the whole path is answered, and the manager's source choice never falls back to the workbook.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] The wizard offers the full source vocabulary: workbook, CSV, JSON, notes, web page, calendar, mail, hand-kept number, desk state with its selector, and research.
- [ ] A mention of reading mail is no longer refused as "sending mail"; only sending or drafting mail is refused.
- [ ] Answering one question does not build the plugin. The build happens only once every question on the chosen path has an answer.
- [ ] The installed manifest names the chosen source type, and a pipeline-backed source (mail, calendar, research) declares no watched file.
- [ ] A mail, calendar, or research plugin renders a tile with content, and its card is not the classic tracker face.
