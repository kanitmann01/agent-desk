# 04: The calendar says what to read before the meeting, and Outlook says who is waiting

**What to build:** a calendar card whose reading turns the next meeting into three research prompts sized to the user's prep window, and an Outlook card that names the threads waiting longest with the reason they are waiting, plus a reply skeleton the user can open in the reply writer and a press that composes a draft in the user's tone.

**Blocked by:** 01, 02.

**Status:** ready-for-agent

- [ ] The calendar family derives three prompts from the next meeting's title, attendees and time, bounded by prepMinutes, and emits them as a checklist or one text line according to density.
- [ ] The digest family names up to three waiting threads with age and the mechanical reason (question asked, no reply sent), reusing the existing scoring rather than a new one.
- [ ] A deterministic reply skeleton is composed from the thread's own subject and greeting, honouring replyTone and replyLength, and is labelled as a skeleton.
- [ ] POST /api/insight/draft discloses the exact payload first, refuses with 409 when the model path is off, and with an injected completer returns a draft that opens in the existing reply writer rather than sending anything.
- [ ] When memory is locked or empty the readings still appear and a note says what was not consulted.
- [ ] tests/test_insight_digest.py and tests/test_insight_agenda.py cover prompts, reminders, skeleton, disclosure, refusal and degrade.
