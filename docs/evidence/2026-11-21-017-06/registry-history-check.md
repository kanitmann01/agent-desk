# Evidence 017-06 6c: the append-only history check bites automatically

The gap (tooling.md F2): hosted CI had no registry job and the local
gate passed no base index, so `_history_reasons`
(`src/agentdesk/registry/ci.py`) ran nowhere: a PR deleting an old
release passed every light green. The local base-index wiring landed
with 4cc901d; this ticket adds the hosted `registry` job to
`.github/workflows/enterprise.yml` (same tool, byte-identical
validator, base index from `git merge-base HEAD origin/main`) and the
test that pins the job (`tests/test_enterprise_workflow.py`), plus the
tool-level proof that already existed
(`tests/test_registry_ci_tool.py::test_tool_blocks_on_truncated_history`).

## A PR deleting an old release, caught by the local gate leg

Run in this ticket's worktree. The working-tree `registry/index.json`
has excel-report's only release line deleted, exactly what such a PR
would merge:

```
$ python tools/registry_ci.py --registry registry \
    --plugins registry/plugins/competitor-watch,registry/plugins/excel-report,registry/plugins/presentation-starter \
    --archive archive/plugins --base-index <merge-base index>
FAIL registry-ci:history-truncated:excel-report:0.1.0
FAIL registry-ci:unindexed-release:0.1.0
REGISTRY-CI FAILED (2)
```

Through the local gate's own leg (`ci_local._registry_gate`, which
resolves the base index the same way, from `git merge-base`):

```
$ python - <<'PY'
import os, sys
sys.path.insert(0, "tools")
import ci_local
ok, detail = ci_local._registry_gate(dict(os.environ))
print("registry gate leg:", "PASS" if ok else "FAIL", "|", detail)
PY
registry gate leg: FAIL | REGISTRY-CI FAILED (2)
```

## The same checkout after restoring the release

```
$ cp index-backup.json registry/index.json
$ python tools/registry_ci.py --registry registry \
    --plugins registry/plugins/competitor-watch,registry/plugins/excel-report,registry/plugins/presentation-starter \
    --archive archive/plugins --base-index <merge-base index>
REGISTRY-CI PASS

restored; registry gate leg: PASS | REGISTRY-CI PASS
```

The hosted job runs the identical command with the identical tool, so
the same refusal now fails the `registry` job on the PR itself.
