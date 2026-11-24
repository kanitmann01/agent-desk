# 08: The fill is shown, and invited when it is missing

**What to build:** submitting a description opens a dialog with a skeleton row for each field while the fill runs, then shows each chosen label and its reason, and says plainly that the fields were filled from the description. Every field stays editable. Without an AI connection the dialog does not open, and the question walk carries one quiet line inviting the manager to add an AI connection so the next description fills itself in.

**Blocked by:** 07.

**Status:** done

- [x] With a connection saved, submitting opens the dialog with a skeleton per field and marks it busy until the fill lands.
- [x] When the fill lands, each row shows its label and reason, and the dialog says the fields were filled from the description and invites correction.
- [x] Every filled field can be changed before continuing, and continuing builds the preview without installing anything.
- [x] Without a connection, the dialog does not open and the walk carries the quiet line linking to the AI connection settings, with no error styling.
- [x] Without a connection, no AI error message appears anywhere in the walk.
- [x] With a connection whose call fails, the dialog says the fill did not run and does not ask the manager to add a connection.
