# 05: A tile refreshes when its source changes

**What to build:** a tile set to update on change refreshes only when its source actually changes: a saved workbook, a modified file or hand-kept number, a changed calendar, new mail, or a saved research answer. Opening the home screen does not count as a change.

**Blocked by:** 03.

**Status:** done

- [x] A workbook tile refreshes after the workbook watch reports a change.
- [x] A calendar or mail tile refreshes after its poll, and only when the reading differs from the stored one.
- [x] A research tile refreshes after a new research answer is saved.
- [x] A file tile and a hand-kept number refresh only when the file's modification time changes.
- [x] Opening the home screen does not re-read a change-driven tile.
