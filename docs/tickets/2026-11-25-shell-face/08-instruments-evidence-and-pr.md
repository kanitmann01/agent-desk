# 08: The walk measures it: instruments, evidence and pull request

**What to build:** the claim of this spec is that every wait lights the face. The pending walk becomes the measurement: it records for each control whether the face lit during the wait, covers the server-rendered pages, and counts the controls where it did not. The ticket then gathers the evidence, writes the rules and the vocabulary down, and opens the pull request for the whole spec.

**Blocked by:** 04: Declared waits on server-rendered pages. 05: Memory page waits light the face. 06: Background truth on every page. 07: The face in the two working dialogs.

**Status:** ready-for-agent

- [ ] The pending walk records a face verdict for each control (`lit`, `idle` or `absent`) and the mood it saw, between the moment the control shows busy and the moment it stops. The metric line gains `face-missing=<n>`, and with `--fail-on` set, a control that met its feedback rule with no lit face is a finding.
- [ ] The selftest gains a planted expectation for each face verdict (a lit wait, an idle face, an absent face) and prints `SELFTEST PASS` with the new counts.
- [ ] The pending pass covers every page the rail reaches, the server-rendered ones included: each appears in the plan with measured states.
- [ ] On the final head at 1280: `face-missing=0`, `dead=0`, `silent=0`, `disabled-only=0`. The counts of controls, instant, meets, native-dialog and skipped are recorded next to the previous wave's AFTER row.
- [ ] The feedback walk exits 0. The layout matrix shows zero new findings outside the 11px class with real and with long strings, and the rail's column keeps its width on every page. Under reduced-motion emulation the eight moods are still poses on a server-rendered page.
- [ ] Evidence under `docs/evidence/2026-11-25-shell-face/`: one photograph per mood per theme for the rail, for a server-rendered page and for each dialog; the reduced-motion poses; the walk numbers; the exact commands.
- [ ] `docs/design-language.md` and `DESIGN.md` say that the shell is the face's one home, and keep the two written exceptions for the face. `GLOSSARY.md` gains shell, rail, island, wait, phase line, mood and the agent's name. README's verdict list and selftest line match the instrument.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the final head. The bundle is rebuilt once from the merged source, and two builds give the same tree. Hosted checks are green.
- [ ] An agent that did not write the code reviews the whole diff and leaves zero open P0 and P1 remarks.
- [ ] The pull request is merged by a merger agent only after the founder's confirmation.
