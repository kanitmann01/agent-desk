"""Registry CI entry point: review a PR's changed plugins, exit nonzero to block.

Stdlib only, runs straight from a checkout (no package install needed):

    python tools/registry_ci.py --registry registry --plugins registry/plugins/a,registry/plugins/b
    python tools/registry_ci.py --registry registry --base-index base-index.json

Output mirrors the validator style: ``FAIL <reason>`` lines, then one
final line, ``REGISTRY-CI PASS`` or ``REGISTRY-CI FAILED (n)``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentdesk.registry.ci import review_registry_changes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Review a PR's changed registry plugins and return the CI exit code.

    --plugins is a comma-separated list of directories and may be empty;
    --base-index is optional, and a path that does not exist is treated as no
    base, which skips the append-only history check instead of failing the
    run. Prints one "FAIL <reason>" line per rejection, then a final verdict:
    0 for REGISTRY-CI PASS, 1 when any check failed.
    """
    parser = argparse.ArgumentParser(prog="registry-ci")
    parser.add_argument("--registry", required=True, type=Path,
                        help="registry root (holds index.json)")
    parser.add_argument("--plugins", default="",
                        help="comma-separated changed plugin directories")
    parser.add_argument("--base-index", type=Path, default=None,
                        help="the base branch index.json for the "
                             "append-only history check")
    args = parser.parse_args(argv)

    plugin_dirs = [Path(p.strip()) for p in args.plugins.split(",") if p.strip()]
    base_text = args.base_index.read_text(encoding="utf-8") \
        if args.base_index and args.base_index.exists() else None

    result = review_registry_changes(args.registry, plugin_dirs,
                                     base_index_text=base_text)
    for reason in result["reasons"]:
        print(f"FAIL {reason}")
    if result["ok"]:
        print("REGISTRY-CI PASS")
        return 0
    print(f"REGISTRY-CI FAILED ({len(result['reasons'])})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
