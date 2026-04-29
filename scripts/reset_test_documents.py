#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


FIXTURES = ("documentazione-source", "documentazione-glossario")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset the sample documentation folders from vendor ZIP archives."
    )
    parser.add_argument("--vendor-dir", default="vendor", help="Directory containing fixture ZIP archives.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned replacements without changing files.")
    args = parser.parse_args()

    vendor_dir = Path(args.vendor_dir).expanduser().resolve()
    if not vendor_dir.exists() or not vendor_dir.is_dir():
        parser.error(f"Vendor directory does not exist: {vendor_dir}")

    for fixture in FIXTURES:
        archive = vendor_dir / f"{fixture}.zip"
        target = vendor_dir / fixture
        if not archive.exists():
            parser.error(f"Missing archive: {archive}")
        if args.dry_run:
            print(f"Would replace {target} from {archive}")
            continue
        if target.exists():
            shutil.rmtree(target)
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(vendor_dir)
        print(f"Replaced {target} from {archive}")

    print("ZIP archives preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
