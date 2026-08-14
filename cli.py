#!/usr/bin/env python3
"""H26 Watchface CLI entry point.

Usage:
    python3 cli.py <command> [options]

Commands:
    compile  - Compile project JSON → .bin watchface
    parse    - Parse .bin → JSON structure
    info     - Quick summary of a .bin file
    verify   - Round-trip test: parse → serialize → compare
    export   - Export .bin → folder/zip with images + project.json
    build    - Build .bin from folder/zip with project.json + images

Examples:
    python3 cli.py compile project.json -o watchface.bin
    python3 cli.py parse watchface.bin
    python3 cli.py info watchface.bin
    python3 cli.py export watchface.bin -o project/
    python3 cli.py build project/ -o watchface.bin
"""

import sys

from h26.cli import main

if __name__ == "__main__":
    sys.exit(main())
