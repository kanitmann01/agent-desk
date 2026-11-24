# O2: How does the feeder run without admin?

Type: research. Claim: unclaimed. Blocked by: none.

## Question

What is the smallest reliable way to run a local feeder on a schedule on Windows and macOS, with no admin rights, no machine-wide install and no OS service?

Compare, with evidence:

- an app-owned background thread while the app runs, on both platforms;
- a per-user Task Scheduler task on Windows, created with `schtasks` or the Task Scheduler COM API;
- a per-user launchd agent on macOS, plus the `launchctl` commands;
- a per-user login item or Start-up shortcut plus an in-app timer;
- a hybrid: the app runs the feeder on start and registers a per-user job for when it is closed;
- any other user-space scheduler the research finds.

For each, state what it needs (rights, paths, user context), how it is installed and removed, how it behaves when Outlook is closed, when the app is closed, when the machine is locked or asleep, and how the app can show the last run and the next run honestly. The recommendation must be platform agnostic first. The answer must include the exact command or API call for the chosen mechanism.

## Answer

Pending. Resolve from the swarm research and record the chosen mechanism, the install and remove commands, the failure modes and the evidence here, then close this ticket and add a line to the map's Decisions so far.
