#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Remove Frameworks debug export fragments that reference missing files.

Dry-run by default. No CMake code is executed and no privileges are acquired.
Run between builds/installations, not concurrently with package deployment.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


HEADER = re.compile(r'^# Generated CMake target import file for configuration "([^"]+)"\.', re.M)
CHECK_START = re.compile(r'^\s*list\(\s*APPEND\s+_cmake_import_check_files_for_', re.M)
CHECK = re.compile(
    r'^\s*list\(\s*APPEND\s+_cmake_import_check_files_for_([^\s()]+)\s+'
    r'((?:"[^"\\\r\n]+"\s*)+)\)', re.M)


def read_export(path: Path, prefix: Path) -> tuple[str, dict[str, list[Path]]]:
    """Read the check lists in standard CMake-generated exports, without eval."""
    if path.is_symlink() or not path.resolve().is_relative_to(prefix):
        raise ValueError("export is a symlink or escapes the selected prefix")
    text = path.read_text(encoding="utf-8")
    header = HEADER.search(text)
    matches = list(CHECK.finditer(text))
    if not header or not matches or len(matches) != len(CHECK_START.findall(text)):
        raise ValueError("not a supported CMake-generated target export")
    targets: dict[str, list[Path]] = {}
    for match in matches:
        paths = targets.setdefault(match[1], [])
        for value in re.findall(r'"([^"]+)"', match[2]):
            value = value.replace("${_IMPORT_PREFIX}", str(prefix))
            if "$" in value or not Path(value).is_absolute():
                raise ValueError("export contains an unresolved or relative file reference")
            paths.append(Path(value))
    return header[1], targets


def stale_references(path: Path, prefix: Path) -> list[Path]:
    """Return missing debug artifacts, regardless of other installed exports."""
    configuration, targets = read_export(path, prefix)
    if configuration.casefold() != "debug":
        raise ValueError("export does not declare the Debug configuration")
    return [item for paths in targets.values() for item in paths if not item.is_file()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", action="append", type=Path,
                        help="installation prefix to scan (repeatable; default: /usr)")
    parser.add_argument("--apply", action="store_true",
                        help="remove confirmed stale exports; otherwise only preview")
    args = parser.parse_args(argv)
    prefixes = sorted({path.resolve() for path in (args.prefix or [Path("/usr")])})
    for prefix in prefixes:
        if not prefix.is_dir():
            parser.error(f"installation prefix does not exist: {prefix}")

    seen = set()
    found = removed = skipped = 0
    for prefix in prefixes:
        directories = [prefix / "lib/cmake", prefix / "lib64/cmake"]
        directories.extend(sorted(prefix.glob("lib/*/cmake")))
        for directory in directories:
            for path in sorted(directory.glob("KF6*/*Targets-debug.cmake")):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                try:
                    info = path.lstat()
                    before = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    missing = stale_references(path, prefix)
                    if not missing:
                        continue
                    found += 1
                    print(f"{'STALE' if args.apply else 'WOULD REMOVE'} {path}")
                    for reference in missing:
                        print(f"  missing: {reference}")
                    if args.apply:
                        # Recheck the fragment and its references before removing it.
                        missing_now = stale_references(path, prefix)
                        info = path.lstat()
                        after = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                        if missing_now != missing or after != before:
                            raise ValueError("export or referenced files changed during inspection; retry when idle")
                        path.unlink()
                        removed += 1
                        print(f"REMOVED {path}")
                except (OSError, UnicodeError, ValueError) as error:
                    print(f"SKIP {path}: {error}", file=sys.stderr)
                    skipped += 1
    if args.apply:
        print(f"Removed {removed} stale debug export(s); skipped {skipped}.")
    else:
        print(f"Dry run: {found} stale debug export(s); skipped {skipped}. Pass --apply to remove.")
    return 1 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
