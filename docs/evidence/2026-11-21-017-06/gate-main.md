# Evidence 017-06: the gate run that proves the ticket

The gate is this ticket's own verifier (spec 017 Testing Decisions): the
grammar leg runs from a checkout under `.worktrees/` and counts a nonzero
tree, and the registry leg feeds the history check the base index. This
file records the branch's full run and the main checkout's pre-fix
behavior on the legs this PR touches.

## The branch's full run (this worktree, rebased onto main 9418699)

The checkout path contains `.worktrees/`, exactly the case 6a fixed
(the pre-fix tool checked zero files here; see
grammar-leg-before-after.md):

```
$ python tools/ci_local.py
agent-desk local CI  (data dir: C:\Users\mannk\AppData\Local\Temp\agentdesk-ci-iwvfil1u)
checkout: D:\20-projects\Personal Agents\.worktrees\017-06-gate
------------------------------------------------------------------------
PASS  py-grammar          0.5s  365 files parse under 3.10
FAIL  pytest            522.7s  2 failed, 2666 passed, 1 skipped, 11 warnings in 520.90s (0:08:40)
PASS  frontend-check      2.8s  tsc --noEmit clean
PASS  frontend-tests      8.9s  Tests  312 passed (312)
PASS  licenses            0.4s  sbom, license gate and notices all clean
PASS  registry-ci         0.2s  REGISTRY-CI PASS
PASS  brand-leak          0.1s  BRAND-LEAK PASS (1 pack(s), 0 hash(es))
------------------------------------------------------------------------
6/7 gates passed in 535s
FAILED gates: pytest
```

The two pytest failures are the pre-existing presentation-pack
byte-compare pair on this machine's zlib, tracked as issue #237, and
they reproduce identically on a clean main 9418699 scratch checkout:

```
$ cd "D:/20-projects/Personal Agents/.scratch/verify-main-9418699"   # detached worktree at 9418699
$ python -m pytest tests/test_presentation_packs.py::test_the_shipped_shells_are_the_neutral_builder \
    tests/test_presentation_render.py::test_a_fake_renderer_shows_a_preview_and_names_itself -q
2 failed in 0.89s
```

Both failures are `AssertionError` byte-compares of built `.pptx`/`.png`
artifacts (deflate bytes differ under this machine's zlib build). Every
other leg passes, including the two this ticket rewires (licenses now
the SBOM chain, registry-ci now with the base index).

## The main checkout at 9418699, before the fix (read-only spot-check)

Main's own `tools/ci_local.py` at its own checkout path, grammar leg:

```
main checkout, main's tool, grammar leg: True | 356 files parse under 3.10
```

356 = src/tests/tools only: the scripts tree is outside main's floor
(6b), and the count is nonzero only because that checkout's path does
not contain `.worktrees/` (6a). Main's licenses leg still runs the
legacy `tools/license_manifest.py` byte-diff (6f deletes it on this
branch), and main's workflow has no registry job (6c adds it).
