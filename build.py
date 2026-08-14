#!/usr/bin/env python3
"""Build script for creating executable with PyInstaller.

Usage:
    python build.py          # Build for current platform
    python build.py --clean  # Clean build artifacts
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def clean():
    """Remove build artifacts."""
    dirs_to_remove = ["build", "dist"]
    files_to_remove = ["*.spec.bak"]

    for d in dirs_to_remove:
        p = Path(d)
        if p.exists():
            print(f"Removing {p}/")
            shutil.rmtree(p)

    for pattern in files_to_remove:
        for f in Path(".").glob(pattern):
            print(f"Removing {f}")
            f.unlink()

    print("Clean complete.")


def build():
    """Build executable using PyInstaller."""
    spec_file = Path("lumen-h26.spec")
    if not spec_file.exists():
        print("Error: lumen-h26.spec not found")
        sys.exit(1)

    print("Building executable with PyInstaller...")
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "PyInstaller", str(spec_file), "--noconfirm"],
        capture_output=False,
    )

    if result.returncode != 0:
        print("Build failed!")
        sys.exit(1)

    print("\nBuild complete!")
    print("Executable location: dist/LumenH26Pro/")

    # Show the main executable
    if sys.platform == "win32":
        exe = Path("dist/LumenH26Pro/LumenH26Pro.exe")
    else:
        exe = Path("dist/LumenH26Pro/LumenH26Pro")

    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"Main executable: {exe} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Build LumenH26Pro executable")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts")
    args = parser.parse_args()

    if args.clean:
        clean()
    else:
        build()


if __name__ == "__main__":
    main()
