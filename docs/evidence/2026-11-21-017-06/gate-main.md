# Evidence 017-06: the main-checkout gate run

Recorded after the ticket's verification instruction: run the local
gate once from the MAIN checkout (read-only) alongside the worktree
run in gate-worktree.md.

The main checkout sits at 33470a1 (the branch base) on `main`, so it
carries none of this ticket's fixes; its run shows the pre-fix state
of the legs this PR touches, including the pre-existing registry
breakage this PR diagnoses (extension-less LICENSE/NOTICE checked out
as CRLF on Windows break the byte-exact digest pins; see the PR body).

Transcript appended below after the run.
