"""List expected Excel files without opening or modifying them."""

import argparse
from pathlib import Path

from backend.importers.sources import SOURCES


def main() -> int:
    parser = argparse.ArgumentParser(description="Check availability of partner Excel files.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data",
        help="Directory containing IEK/ and Systeme electric/ (default: repository data/).",
    )
    args = parser.parse_args()
    missing = 0
    for source in SOURCES:
        exists = source.path(args.data_dir).is_file()
        missing += not exists
        status = "FOUND" if exists else "MISSING"
        print(f"{status}: {source.brand}/{source.filename} [{source.purpose}]")
    print(f"Files found: {len(SOURCES) - missing}/{len(SOURCES)}. Contents not validated.")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
