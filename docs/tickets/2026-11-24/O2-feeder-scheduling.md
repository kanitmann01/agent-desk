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

Chosen: the app's own daemon timer, on both platforms, plus one pass at startup.

Why this and not an OS scheduler:

- The PRD bans autostart persistence until Security approves (`docs/PRD.md:19`), and the IT statement says "No Run key, no scheduled task, no service" and "the app runs only while you keep it open" (`src/agentdesk/server/touches.py:58-59`, pinned by `tests/test_server_it_surface.py:120-122`). A per-user Task Scheduler entry or a `launchd` agent changes that promise and needs sign-off.
- The app already schedules mail and calendar with daemon `threading.Timer` chains (`src/agentdesk/mail/watcher.py:344-377`, `src/agentdesk/calendar/watcher.py:441-474`) and runs one immediate pass at startup (`app.py:7897-7936`). The feeder can run inside that pattern, so there is no new scheduler, no install step and no OS-specific code.
- The app is a desktop app the user opens. A pass at startup plus the existing 30-minute mail cadence is enough for a digest. When the app is closed, collection pauses; the next start catches up from the collector's own window. That limit is honest and must be said in Settings.

Install and remove: none. The feeder is constructed when `mail_enabled` and `mail_feeder` are both on, started with the mail watcher, and stopped with it. No command is needed. The app must update the IT statement because it now starts a local read-only helper while it is open; the statement remains true that no task, service or autostart entry is created.

Failure modes: the timer chain survives a collector exception; the next tick still runs. A lock file prevents overlapping passes. If the app is closed, the last run and coverage window are shown, never a false "live" claim.

Deferred: a per-user Task Scheduler task on Windows or a per-user `launchd` agent on macOS would collect while the app is closed. That is a separate decision with Security sign-off, not part of v1.

## Resolution (2026-11-24)

Resolved and implemented as chosen. The feeder runs inside `MailWatch.poll()` before the folder read and once at startup, through an injected callable, and it has its own run lock (`outlook-feeder.lock`). It is constructed only when `mail_enabled` and `mail_feeder` are both on, and stopped with the watcher. No OS task, service, login item or autostart entry is created; the IT statement and `tests/test_server_it_surface.py` were updated to say the alert reader runs only while the app is open.
