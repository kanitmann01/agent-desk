"""CLI implementation: argument parsing, output formatting, exit codes.

Exit codes: 0 pass, 1 validation failure, 2 usage or IO error.
"""

import argparse
import json
import sys

from .core import validate_plugin
from .reader import ValidatorIOError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentdesk-validator",
        description="Validate a Class D plugin (directory or zip): manifest in, verdict out.",
    )
    parser.add_argument("path", help="plugin directory or .zip to validate")
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="machine-readable verdict (deterministic bytes for the same input)",
    )
    args = parser.parse_args(argv)

    try:
        verdict = validate_plugin(args.path)
    except ValidatorIOError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(verdict.as_dict(), sort_keys=True, indent=2))
    else:
        for failure in verdict.failures:
            print(f"FAIL {failure.code}: {failure.message}")
        if verdict.ok:
            print("PASS")
        else:
            print(f"FAILED ({len(verdict.failures)})")
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
