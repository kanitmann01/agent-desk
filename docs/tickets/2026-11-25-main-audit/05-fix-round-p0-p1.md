# 05: Fix round for P0 and P1

**What to build:** every confirmed P0 and P1 from the findings register is fixed on one integration branch, each with a regression test. A review agent that did not write the fixes reviews the fix diff, and the walks that could see the changes are taken again, so main is left in a state that was reviewed, walked and seen.

**Blocked by:** 03, 04.

**Status:** ready-for-agent

- [ ] Every confirmed P0 and P1 is fixed, or re-triaged with a written reason that the founder accepts. The register names the fix commit for each one. Nothing is dropped without a record.
- [ ] Each fix comes with a regression test that fails on the audited commit without the fix (that failing run is recorded) and passes with it.
- [ ] The fix diff passes a review by an agent that did not write it, with zero open P0 and P1 remarks on the diff.
- [ ] Re-walk after the fixes: the pending walk (dead 0, silent 0, disabled-only 0), the layout matrix for every page the fixes touch, and the feedback walk with exit 0. Zero new findings against the numbers of ticket 04.
- [ ] `python tools/ci_local.py` prints `7/7 gates passed` and `CI PASS` on the final head. The committed bundle is rebuilt once from the merged source, and two builds give the same tree.
- [ ] The pull request is merged by a merger agent only after the founder's confirmation.
