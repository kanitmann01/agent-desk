# 07: The description fills the fields in

**What to build:** with an AI connection saved, a manager's plain-English description fills in the source, the detail that source needs, the show, the look, and the update mode, plus one short reason for each. The fill may only pick from the choices the questions would offer, so it can never widen what a plugin reads or introduce a source the wizard cannot build.

**Blocked by:** 02, 03.

**Status:** ready-for-agent

- [ ] With a scripted model reply, "a morning list of my mail" fills My mail, the items that need me, a list, and a morning clock.
- [ ] A returned source outside the vocabulary leaves the source unanswered rather than defaulting to the workbook.
- [ ] A returned show, look, or update mode outside the legal set for that field is dropped and left for the manager.
- [ ] A detail the reply cannot supply (a web address, a file pattern) is asked of the manager.
- [ ] The fill call is recorded as the existing wizard model row, and a failing call leaves every field unanswered.
