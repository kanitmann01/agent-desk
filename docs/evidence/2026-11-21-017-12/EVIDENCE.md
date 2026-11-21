# Evidence: ticket 017-12, deterministic presentation tests (spec 017)

Captured on 2026-11-21 from the ticket branch worktree
(`ticket/017-12-presentation-tests`, fresh from main 9418699), on the
machine the ticket names: Python 3.14.5 shipping zlib-ng
(`zlib.ZLIB_RUNTIME_VERSION` = `1.3.1.zlib-ng`) and `core.autocrlf=true`.
No production code changed. No byte in the working tree was restored by
hand at any point.

## Family 1: the shell byte-compare test asserted deflate bytes

The committed shells (`registry/plugins/presentation-starter/shells/`)
were produced by `pack_zip` on a stock-zlib machine. zlib-ng deflates the
same decompressed bytes differently byte-wise, so
`test_the_shipped_shells_are_the_neutral_builder` compared machine
compression accidents, not the product: the shell's part set and each
part's decompressed content.

- `before-packs-zlib-ng.txt`: `1 failed, 11 passed`. The failure is the
  raw deflate mismatch (`At index 18 diff: b'X' != b'Z'`, the first byte
  of the first entry's compressed size).
- `after-packs-zlib-ng.txt`: `12 passed`. The test now compares
  `read_parts(committed) == read_parts(build_shell(...))`:
  `read_parts` returns every zip entry keyed by name with its
  decompressed content, so dict equality is exactly the entry set plus
  each entry's decompressed bytes.

Why the fix holds on stock zlib without running one: the comparison
never touches compressed bytes, so it is zlib-independent by
construction; a machine's zlib flavor cannot change either side of the
equality's meaning (the committed file's decompressed parts are fixed by
the blob, the fresh build's parts are fixed by the same string literals).

## Family 2: the starter digest-pin tests vs a CRLF working tree

`tree_digest` (the same function production install uses) hashes
working-tree bytes. Before PR #238, the extension-less
`presentation-starter/LICENSE` and `NOTICE` sat under `* text=auto`
alone, so an `autocrlf=true` checkout smudged them to CRLF and the
registry pin `e3aeef94d01e...` could never match.

The fix chosen: rely on the .gitattributes pin (already in main via
PR #238, `text eol=lf` for both files); this PR adds zero code for this
family. Recorded reasoning, per the ticket's pick-the-smaller-correct
instruction:

- The production install path (`install_from_registry` staging a local
  release, `tree_digest(staged)`) hashes the same working-tree bytes the
  tests hash. A `git cat-file` fix inside the test would go green while
  real installs from a stale checkout stayed broken: the test would lie.
- The attributes pin fixes the root cause for the tests and the product
  at once, and costs zero new lines (it has already landed). It is the
  smaller correct fix.

`before-digest-pins-crlf.txt` reproduces the old failure mode: with the
two files smudged to CRLF exactly as a pre-#238 autocrlf checkout left
them, both digest-pin tests fail (`content sha256 f5776b20d7d8 does not
match the pinned e3aeef94d01e`), plus the install test's
`RegistryError`. `2 failed` on the digest pins.

The acceptance criterion, a fresh `autocrlf=true` checkout with no
manual byte restoration, is proven in-session, not hand-argued:

- `git check-attr text eol -- registry/plugins/presentation-starter/{LICENSE,NOTICE}`
  answers `text: set`, `eol: lf` for both.
- Both files were deleted and restocked with `git checkout --`; the
  restocked bytes are LF-only (11358 and 388 bytes, the committed sizes)
  and `git status` stays clean.
- `after-digest-pins-fresh-restock.txt`: `2 passed` from those restocked
  bytes, no hand-conversion anywhere.

(An old checkout that predates the attributes still needs one
`git checkout -- <files>` to restock; that is git's own restock, not a
manual byte repair, and any fresh clone or worktree is correct from the
first checkout.)

## The full gate

`gate-transcript.txt` is the `python tools/ci_local.py` run from the
worktree checkout (frontend `node_modules` reached through a junction to
the main checkout's install; no `npm ci`, no byte restoration):

- PASS py-grammar, frontend-check (tsc clean), frontend-tests (vitest
  312 passed), licenses, registry-ci (REGISTRY-CI PASS; the digest pins
  verify against the working-tree bytes), brand-leak.
- FAIL pytest: `1 failed, 2676 passed, 2 skipped`. The pytest cache the
  gate run left behind (`lastfailed`) names the one failure, and it is
  exactly the out-of-scope render test above, the machine-dependent 404
  that fails identically on clean main and needs a production change
  this ticket forbids. Nothing else in the suite fails: both families
  this ticket owns are green inside the same run.

`presentation-family-worktree.txt` is the direct run of the five
presentation files this ticket touches from the worktree: `44 passed`
(packs, writer, fit, pipeline, research).

## Out of scope, reported

`tests/test_presentation_render.py::test_a_fake_renderer_shows_a_preview_and_names_itself`
still 404s on this machine, and the same single-test command fails on
clean main 9418699 (`cd` to a clean main checkout,
`python -m pytest "tests/test_presentation_render.py::test_a_fake_renderer_shows_a_preview_and_names_itself" -q`).
It is not this ticket's family: `render_deck` stores image paths via
`str(path.relative_to(...))`, which on Windows yields
`preview\slide1.png`, while the download route matches
`endswith("/" + part)`, so the png part 404s on Windows only. The fix is
a production change (`as_posix()` in `src/agentdesk/presentations/render.py`
or the route's match), which ticket 017-12 forbids.
