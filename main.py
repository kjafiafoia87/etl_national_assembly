#!/usr/bin/env python3
"""Repository-level CLI entry point."""

from __future__ import annotations

import sys

from convert_acteurs_to_csv import main as deputies_main
from import_data.main import main as import_data_main


IMPORT_DATA_COMMANDS = {"download", "convert", "csv", "all"}


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in IMPORT_DATA_COMMANDS:
        import_data_main(sys.argv[1:])
        return
    deputies_main()


if __name__ == "__main__":
    main()
