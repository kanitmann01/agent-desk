# 03: Background moods and the agent loop signal

**What to build:** carry live background pass state (`running`, `currentStep`, and `lastOk`) from the supervised agent loop through `dashboard_state` onto the dashboard and agent-loop payloads, follow `GET /api/agent-loop` every 2 seconds while a pass is running, and drive the face's background moods (`working` during an active pass, `done` only when `lastRunTs` advances between two visible polls and `lastOk` is true, `waiting` when decisions or inbox items wait on the user, and `blocked` when a fatal desk check or broken state exists) while keeping foreground requests at higher priority and never treating an unconfigured desk as broken.

**Blocked by:** 02: The rail brand row and user-driven waits.

**Status:** ready-for-agent

- [ ] `agentloop` tracks `currentStep` and `lastOk`, setting and clearing `currentStep` around `step.run` under the state lock and clearing it in `finally` without ever holding the lock across `step.run`.
- [ ] `dashboard_state` includes the supervised agent loop's active running state (`running`), `currentStep`, and `lastOk` alongside its existing summary fields without breaking any pinned payload or existing API consumer.
- [ ] Pytest coverage on the `agentloop` and `dashboard_state` seams verifies active, idle, and broken loop states in the payload and includes a deadlock test where a running step calls `status()` without blocking.
- [ ] While a background pass is actively running, the dashboard polls `GET /api/agent-loop` on a 2-second cadence until the pass settles.
- [ ] The dashboard maps background signals to the face through `useFaceActivity`: active background pass drives `working` (`pass` priority), pending decisions or waiting inbox items drive `waiting`, fatal desk checks or broken loop/source states drive `blocked`, and transient `done` fires only when `lastRunTs` advances between two visible polls and `lastOk` is true.
- [ ] "Blocked means broken" holds strictly: an empty or unconfigured fresh desk (or Sample data mode) stays `idle` rather than showing `blocked`.
- [ ] Mood priority holds end to end: foreground user requests and transient `done` always outrank background `blocked`, `waiting`, `pass`, `listening`, and `idle`.
- [ ] Frontend tests verify background mood mapping, 2-second follow polling, the `lastRunTs` advance plus `lastOk` trigger for `done`, and priority preemption; both pytest and Vitest suites pass.
