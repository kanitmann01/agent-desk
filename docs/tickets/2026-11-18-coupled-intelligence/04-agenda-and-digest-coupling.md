# 04: The calendar says what to read before the meeting, and Outlook says who is waiting

**What to build:** a calendar card whose reading turns the next meeting into three research prompts sized to the user's prep window, and an Outlook card that names the threads waiting longest with the reason they are waiting, plus a reply skeleton the user can open in the reply writer and a press that composes a draft in the user's tone.

**Blocked by:** 01, 02.

**Status:** done

- [x] The calendar family derives up to three prep prompts from the next meeting's title and time, bounded by prepMinutes, and emits them as a checklist or one text line according to density. The agenda seam carries title, time, meta and prep items but no attendee list, so no prompt names a person rather than inventing one.
- [x] The digest family names the one waiting thread with the best mechanical reason (a focus topic or a recalled fact names it), reuses the card's own ranking instead of scoring threads again, and leaves the card's list to show the rest and their ages.
- [x] A deterministic reply skeleton is composed from the thread's own subject and greeting, honouring replyTone and replyLength, and is labelled as a skeleton.
- [x] POST /api/insight/draft discloses the exact payload first, refuses with 409 when the model path is off, and with an injected completer returns a draft that opens in the existing reply writer rather than sending anything.
- [x] When memory is locked or empty the readings still appear and a note says what was not consulted.
- [x] tests/test_insight_digest.py and tests/test_insight_agenda.py cover prompts, reminders, skeleton, disclosure, refusal and degrade.
