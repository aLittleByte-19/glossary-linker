#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glossary_linker.core.compiler import clean_latex_artifacts, iter_latex_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove LaTeX compilation artifacts under a directory.")
    parser.add_argument("root", nargs="?", default=".", help="Directory to clean. Defaults to the current repo.")
    parser.add_argument("--dry-run", action="store_true", help="Print files that would be removed without deleting them.")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        parser.error(f"Root directory does not exist: {root}")

    if args.dry_run:
        removed = iter_latex_artifacts(root)
    else:
        removed = clean_latex_artifacts(root)

    for path in removed:
        print(path)
    print(f"{'Would remove' if args.dry_run else 'Removed'} {len(removed)} LaTeX artifact(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
