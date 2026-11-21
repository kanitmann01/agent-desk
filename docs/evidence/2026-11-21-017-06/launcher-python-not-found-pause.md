# Evidence 017-06 6e: the Python-not-found message stays on screen

The bug (tooling.md F4): `tools/agent-desk.cmd` printed the honest
"Python not found" message and exited, so a double-clicked window
flashed and closed; the person the message was written for could never
read it. `tools/probe.cmd` pauses for exactly this reason, and the old
`test_agent_desk_cmd_leaves_no_console_open` pinned the no-pause bug.

## Transcript: the failure path, forced on a machine that has Python

The launcher run under a PATH with no python, py or uv on it, from this
ticket's worktree (the piped newline is what released the pause; a
human presses a key):

```
$ echo | env -i SystemRoot="C:\\Windows" PATH="/tmp/empty-path-bin" \
    /c/Windows/system32/cmd //c "tools\\agent-desk.cmd"
Python not found on PATH and no uv. Install Python 3.10+ for your user, or install uv.
Press any key to continue . . .
```

The message is readable and the window holds. The pause genuinely
blocks on the keypress: the same run with stdin closing immediately
finishes in 0.06s, and with stdin held open for 6s the process is still
inside `pause` and exits at 6.04s, exactly when the pipe closes.

The message and pause survive the rebase onto main 9418699 verbatim.
On the fixed launcher the pause exists only in the failure tail: every
success rung starts the server and jumps past it, which
`tests/test_agent_desk_cmd.py::test_agent_desk_cmd_success_paths_leave_no_console_open`
pins (no `pause` before the failure echo) alongside
`test_agent_desk_cmd_pauses_on_the_python_not_found_path`.

Screenshot note: the console pause is captured as a transcript because
a real double-click window cannot be screenshotted from the harness;
the transcript shows the pause line the window now waits on.
