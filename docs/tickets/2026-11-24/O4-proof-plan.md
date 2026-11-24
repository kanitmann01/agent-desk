# O4: What is the proof plan?

Type: task. Claim: unclaimed. Blocked by: O1, O2, O3.

## Question

What must the implementation prove, on this machine, without touching real mail, before the spec is called decision-ready?

Produce:

- a synthetic fixture set that exercises every header field, a malformed file, a missing profile and an empty source;
- the exact commands for the feeder self-check, the app tests and a local end-to-end run;
- the evidence to record (command output, file list, app status, screenshots if a UI changes);
- the test that fails if the feeder starts reading bodies, makes a network call, or shows a number in an attention state.

## Answer

Pending. Resolve after O1 to O3, then close this ticket and add a line to the map's Decisions so far.
