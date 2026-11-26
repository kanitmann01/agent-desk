# 08: Proof: readiness check, render pass, evidence and pull request

**What to build:** the proof that a deck from each template is good, gathered in one place and repeatable. The readiness walk gains one numbered check that builds a deck from each template. Every layout of every template and variant is rendered through both renderers, and each image is read. The evidence holds contact sheets and a before-and-after for one brief. Then the pull request for the whole spec.

**Blocked by:** 06: The form path fills every role. 07: The pack ships.

**Status:** ready-for-agent

- [ ] The readiness walk gains one numbered check: a deck builds from each template through the tool path and passes the package checks. `python tools/demo_readiness.py` prints `METRIC ready=28` with 0 FAIL.
- [ ] The render pass is complete: every layout of every template and variant, through PowerPoint and through LibreOffice (14 roles, 3 templates, 2 variants, 2 renderers: 168 images). Every image has a recorded verdict. Zero clipped text, zero overlapping boxes, nothing outside the half-inch margin.
- [ ] Contact sheets per template and variant, and a before-and-after for one brief (the starter against each new template, same brief, same recipe), are committed under `docs/evidence/2026-11-25-presentation-templates/` with the exact commands.
- [ ] The status line of Spec 021 and `docs/presentation-packs.md` name the new plugin, and README names the templates.
- [ ] Two follow-up issues are filed and linked here: native chart objects, and template packs installed from the marketplace not being discovered.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the final head. Hosted checks are green.
- [ ] An agent that did not write the code reviews the whole diff and leaves zero open P0 and P1 remarks.
- [ ] The pull request is merged by a merger agent only after the founder's confirmation.
