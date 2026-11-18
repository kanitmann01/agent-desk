"""The registry command line: list what is available, install pinned.

Output style matches the validator: ``FAIL <code>: <message>`` on
refusal, exit code 1; ``OK`` lines on success, exit code 0.
"""
from __future__ import annotations

import argparse
import sys

from .index import RegistryIndexError, load_index
from .install import RegistryError, install_from_registry


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand and return its exit code.

    The list command prints one line per plugin and exits 0. Install prints OK
    for a verified install, or FAIL <code>: <message> and exit 1 when the index
    or the validator refuses it.
    """
    parser = argparse.ArgumentParser(prog="agentdesk.registry")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list registry plugins")
    listing.add_argument("--registry", required=True)

    install = sub.add_parser("install", help="install one pinned release")
    install.add_argument("--registry", required=True)
    install.add_argument("--plugin", required=True)
    install.add_argument("--version", required=True)
    install.add_argument("--sha256", default=None, help="expect this exact digest")
    install.add_argument("--dest", required=True)

    args = parser.parse_args(argv)

    if args.command == "list":
        try:
            with open(args.registry and f"{args.registry}/index.json", encoding="utf-8") as handle:
                index = load_index(handle.read())
        except (OSError, RegistryIndexError) as exc:
            print(f"FAIL index-unreadable: {exc}")
            return 1
        for plugin in index.plugins:
            print(f"{plugin.id} {plugin.publisher} {plugin.latest} "
                  f"risk={plugin.risk} class={plugin.class_}")
        return 0

    if args.command == "install":
        try:
            result = install_from_registry(
                args.registry, args.plugin, version=args.version,
                sha256=args.sha256, destination=args.dest)
        except (RegistryError, RegistryIndexError) as exc:
            code = getattr(exc, "code", "install:refused")
            print(f"FAIL {code}: {exc}")
            return 1
        print(f"OK {result['plugin']}@{result['version']} "
              f"sha256={result['sha256']} -> {result['path']}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
