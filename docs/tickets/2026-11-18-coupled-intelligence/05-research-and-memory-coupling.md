# 05: Research continues from the last answer, and memory is consulted where a card has a subject

**What to build:** the research card proposes the next questions from the entities of the last answer and the user's focus topics, and every card that has a subject asks the memory bank what it already knows about it — attributed, bounded, read-only.

**Blocked by:** 01, 02.

**Status:** ready-for-agent

- [ ] The research family derives up to three next questions from the last answer's entities plus focus topics, and one line when there is no answer yet.
- [ ] A shared recall helper turns a card subject into at most three attributed memory lines through the context's read-only callable, never writing.
- [ ] Sealed, absent or empty memory yields one note naming the reason, never an exception and never silently blank.
- [ ] Memory lines are trimmed to a bounded character budget and never quoted verbatim beyond that budget.
- [ ] tests/test_insight_research.py covers entity extraction, focus-topic steering, the no-answer line, and the sealed-bank note.
