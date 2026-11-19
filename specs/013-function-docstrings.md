# 013 — Function docstrings across the codebase

## Problem Statement

A caller in agent-desk cannot tell what a function promises without reading its body. The module headers explain the design, but the functions inside them do not: 886 of 1,745 first-party Python functions in scope carry no docstring (51%), and the TypeScript frontend is the same story. The worst files are the ones other code leans on — the HTTP server (86 undocumented functions), the marketplace API (83), the plugin runtime (29) and sources (35) — so a plugin author, a new contributor, or an editor hover tooltip gets a name and a parameter list, and nothing about contract, units, side effects or what is raised.

## Solution

Every function and method in first-party source carries a docstring that states what it does, what it returns, what it raises and the decisions a reader cannot infer from the signature. The convention is written down once, a coverage gate in the test suite holds the line so it cannot drift, and the work lands as directory-sized batches that are provably docstring-only. No behaviour changes land in this spec.

## User Stories

1. As a maintainer, I want every function to say what it does in one sentence, so that I can skim a module and know its behaviour without reading bodies.
2. As a reviewing engineer, I want a function that can raise to name the exception and the condition in its docstring, so that I can judge error handling from the diff alone.
3. As a plugin author, I want the plugin interfaces documented with their lifecycle expectations, so that I can implement one against the docstring instead of reverse-engineering the runtime.
4. As a new contributor, I want units, ranges and formats stated where they matter (bytes, ISO dates, cents, percentages), so that I do not pass the wrong thing by accident.
5. As an editor user, I want hover documentation to show a real summary and return contract instead of the first line of the body, so that I can call unfamiliar code without jumping into it.
6. As an on-call engineer, I want side effects — files written, network calls, rows mutated — called out in the docstring, so that I can tell a pure helper from one that touches the machine.
7. As a coding agent, I want docstrings dense enough to serve as the interface contract, so that a behaviour change shows up as a docstring diff rather than as a silent assumption.
8. As a maintainer, I want a failing test when a new function arrives without a docstring, so that the convention survives contributors who never read the style guide.
9. As a maintainer, I want each batch to be provably docstring-only, so that I can review eighty functions without hunting for a smuggled behaviour change.
10. As a maintainer, I want the coverage ratchet to shrink as batches land, so that progress is visible and partial work cannot silently regress.
11. As a release engineer, I want the full suite green on every batch, so that documentation work never blocks a release.
12. As a reader of the TypeScript frontend, I want the same convention in JSDoc form, so that both halves of the product read alike.

## Implementation Decisions

- **Scope** is first-party source: Python under `src/agentdesk`, `tools/` and `scripts/`; TypeScript/TSX under `frontend/src`. Tests, generated files (route trees, SPA bundle), vendored code and `demo/` are out of scope.
- **One convention, written once** in `docs/docstrings.md`: a one-line imperative summary; then, where the signature does not already say it, a short paragraph on contract, units and decisions; `Args:`/`Returns:`/`Raises:` only when a parameter, a return shape or a raised exception is not obvious from the signature. No restating the signature, no type duplication the annotations already carry, no Sphinx `:param` tags. The existing house voice — terse, explaining why — is the target, not a generic template.
- **Docstring-only diffs.** A batch is accepted only if a code fingerprint is unchanged: the module AST with docstrings stripped must be identical before and after (TypeScript: source with JSDoc blocks stripped). This is what makes an eighty-function diff reviewable.
- **A ratchet, not a big bang.** `tools/docstring_gate.py` walks the scoped roots, collects every function and method without a docstring as a qualified name, and compares it with `docs/docstring-baseline.txt`; it fails when a name appears that the baseline does not list. Each batch deletes its own lines. The baseline ends empty and the file is then deleted.
- **The gate is a test.** `tests/test_docstring_gate.py` runs the gate, so CI and the implement workflow see the same signal. No new dependencies: `ast` only.
- **Batches are directory-shaped.** Docstring coverage is a wide refactor, not a vertical slice: no batch can change behaviour, so the useful unit is a package that one reviewer can hold at once. Sizes run from 55 to 161 functions.
- **Corrections are in scope only when code proves a docstring wrong**, and each correction is called out in the batch's report rather than buried in the diff.

## Testing Decisions

- The only new seam is the gate. It reads source text and AST, never imports the application, so it is fast and cannot fail for environment reasons.
- Behaviour stays covered by the existing suite (140 test files, `pytest`, harness in `tests/conftest.py`), run unchanged on every batch. No test asserts on docstring wording, only on presence — a docstring is contract, not behaviour.
- Prior art for source-level invariants lives in the suite already (source-inspecting tests: tests/test_demo_walkthrough_exists.py, tests/test_validator_codes.py, tests/test_ci_local_tool.py); the gate follows that shape instead of inventing a new one.

## Out of Scope

- Rewriting module headers, class docstrings or comments — they are already written and this spec does not relitigate them.
- Adding type annotations, refactoring signatures, renaming.
- Documentation outside the source: README, `docs/`, `specs/`.
- Docstrings for tests, fixtures, generated or vendored files.
- A linter dependency (ruff/pydocstyle) — the gate is a test so the toolchain stays as it is.

## Further Notes

- The count of record is the gate's output, not this document: 1,745 functions in scope, 886 without a docstring, measured with `ast` on commit daaa8d6.
- The frontend batch's size is established by the gate's TypeScript pass when that ticket starts, so its ticket states a ceiling rather than a number.
