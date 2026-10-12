#!/usr/bin/env python3
"""Version bump scripts for SonicDE repos.

Reads the explicit Plasma, Frameworks, and System repository lists, updates
existing release version fields in CMakeLists.txt, commits any change, and
creates a tag even when no CMake version fields exist. Unlike KDE's release scripts,
no second "bump to next dev version" commit is created -- we make patch
releases against these tagged versions (e.g. 6.7.4.1).

Usage:
    version_bump.py plasma <version> [--dry-run] [--list]
    version_bump.py frameworks <version> [--dry-run] [--list]
    version_bump.py system <version> [--dry-run] [--list]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------
#
# Repository membership comes only from version-repos-<category>.list.
# These replacement functions edit existing release fields, not select repos.

PLASMA_VAR = "PROJECT_VERSION"
FRAMEWORKS_VAR = "KF_VERSION"
SYSTEM_VARS = (
    "RELEASE_SERVICE_VERSION_MAJOR",
    "RELEASE_SERVICE_VERSION_MINOR",
    "RELEASE_SERVICE_VERSION_MICRO",
)


def _replace_quoted_set(content: str, var: str, value: str) -> str:
    """Replace ``set(VAR "old")`` (or ``set (VAR "old")``) with the new value.

    Handles optional whitespace between ``set`` and ``(`` and after ``(``,
    and preserves any trailing comment or closing ``)``.
    """
    pattern = rf'set\s*\(\s*{re.escape(var)}\s+"[^"]*"'
    replacement = f'set({var} "{value}"'
    return re.sub(pattern, replacement, content)


def _replace_ecm_version(content: str, version: str) -> str:
    """Replace the version in ``find_package(ECM X.Y.Z ... NO_MODULE)``.

    Handles optional whitespace, optional REQUIRED, and ``set (`` spacing.
    Only matches a literal version (not a ``${...}`` variable).
    """
    pattern = r'(find_package\s*\(\s*ECM\s+)\d+\.\d+\.\d+(\s+)'
    return re.sub(pattern, rf'\g<1>{version}\g<2>', content)


def _replace_plasma_version(content: str, version: str) -> str:
    content = _replace_quoted_set(content, PLASMA_VAR, version)
    # sonic-breeze-sddm declares its release version directly in project().
    # Variable-based project versions are already handled by set() above.
    pattern = r'(\bproject\s*\([^)]*?\bVERSION\s+)("?)(\d+\.\d+\.\d+(?:\.\d+)?)\2(?=\s|\))'
    return re.sub(pattern, lambda match: f'{match[1]}{match[2]}{version}{match[2]}', content, count=1)


def _replace_frameworks_version(content: str, version: str) -> str:
    """Update all three Frameworks version locations.

    1. ``set(KF_VERSION "old")``           -> ``set(KF_VERSION "new")``
    2. ``set(KF_DEP_VERSION "old")``       -> ``set(KF_DEP_VERSION "new")``
    3. ``find_package(ECM old ... NO_MODULE)`` -> ``find_package(ECM new ... NO_MODULE)``
    """
    content = _replace_quoted_set(content, FRAMEWORKS_VAR, version)
    content = _replace_quoted_set(content, "KF_DEP_VERSION", version)
    content = _replace_ecm_version(content, version)
    return content


def _replace_system_version(content: str, version: str) -> str:
    """Replace the three RELEASE_SERVICE_VERSION_* variables."""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"system version must be X.Y.Z, got {version}")
    for var, part in zip(SYSTEM_VARS, parts):
        content = _replace_quoted_set(content, var, part)
    return content


CATEGORIES: dict[str, dict] = {
    "plasma": {
        "replace": _replace_plasma_version,
    },
    "frameworks": {
        "replace": _replace_frameworks_version,
    },
    "system": {
        "replace": _replace_system_version,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_version(version: str) -> bool:
    """Return True if *version* looks like ``X.Y.Z``."""
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _find_repos(root: Path, category: str) -> list[str]:
    """Read the maintained list; never infer membership from CMake or tags."""
    roster = root / "scripts" / f"version-repos-{category}.list"
    repos: list[str] = []
    for number, line in enumerate(roster.read_text(encoding="utf-8").splitlines(), 1):
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ValueError(f"{roster}:{number}: invalid repository name {name!r}")
        if name in repos:
            raise ValueError(f"{roster}:{number}: duplicate repository {name!r}")
        repos.append(name)
    return sorted(repos)


def _get_current_version(cmake: Path, category: str) -> str | None:
    """Extract the current version from a CMakeLists.txt."""
    content = cmake.read_text(encoding="utf-8")
    if category == "system":
        majors = re.findall(
            rf'set\s*\(\s*{re.escape(SYSTEM_VARS[0])}\s+"([^"]*)"', content
        )
        minors = re.findall(
            rf'set\s*\(\s*{re.escape(SYSTEM_VARS[1])}\s+"([^"]*)"', content
        )
        micros = re.findall(
            rf'set\s*\(\s*{re.escape(SYSTEM_VARS[2])}\s+"([^"]*)"', content
        )
        if majors and minors and micros:
            return f"{majors[0]}.{minors[0]}.{micros[0]}"
        return None

    var = PLASMA_VAR if category == "plasma" else FRAMEWORKS_VAR
    matches = re.findall(rf'set\s*\(\s*{re.escape(var)}\s+"([^"]*)"', content)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------


def bump_category(
    root: Path,
    category: str,
    version: str,
    dry_run: bool = False,
    push: bool = True,
) -> int:
    """Bump all repos in *category* to *version*.

    Returns the number of repos processed.
    """
    cat = CATEGORIES[category]
    repos = _find_repos(root, category)
    if not repos:
        print(f"[{category}] no matching repos found", file=sys.stderr)
        return 0

    processed = 0
    for repo_name in repos:
        repo_dir = root / "src" / "sonicde" / repo_name
        cmake = repo_dir / "CMakeLists.txt"

        # Do not accidentally run git in the enclosing builder repository.
        if not (repo_dir / ".git").exists():
            print(f"[{repo_name}] repository checkout missing, skipping",
                  file=sys.stderr)
            continue

        tag = version
        existing_tag = _git(repo_dir, "show-ref", "--verify", "--quiet", f"refs/tags/{tag}")
        if existing_tag.returncode == 0:
            print(f"[{repo_name}] tag {tag} already exists, skipping")
            continue
        if existing_tag.returncode != 1:
            print(f"[{repo_name}] cannot check tag {tag}: {existing_tag.stderr.strip()}", file=sys.stderr)
            continue

        current = _get_current_version(cmake, category) if cmake.exists() else None
        content = cmake.read_text(encoding="utf-8") if cmake.exists() else ""
        new_content = cat["replace"](content, version)
        if category == "frameworks" and repo_name == "sonic-frameworks-cmake-modules":
            new_content = _replace_quoted_set(new_content, "VERSION", version)
        cmake_changed = new_content != content

        if dry_run:
            if cmake_changed:
                print(f"[{repo_name}] would bump {current or 'CMake version'} -> {version}, tag {tag}")
            else:
                print(f"[{repo_name}] would tag {tag} (no CMake version change)")
            continue

        # Check for dirty working tree
        status = _git(repo_dir, "status", "--porcelain", "--untracked-files=no")
        if status.returncode != 0:
            print(f"[{repo_name}] cannot check working tree: {status.stderr.strip()}", file=sys.stderr)
            continue
        if status.stdout.strip():
            print(
                f"[{repo_name}] working tree not clean, skipping",
                file=sys.stderr,
            )
            continue

        # Commit only an actual CMake update; tag-only repos need no empty commit.
        if cmake_changed:
            cmake.write_text(new_content, encoding="utf-8")
            add_result = _git(repo_dir, "add", "CMakeLists.txt")
            if add_result.returncode != 0:
                print(f"[{repo_name}] staging failed: {add_result.stderr.strip()}", file=sys.stderr)
                continue
            commit_result = _git(repo_dir, "commit", "-m", f"Release {version}")
            if commit_result.returncode != 0:
                print(f"[{repo_name}] commit failed: {commit_result.stderr}", file=sys.stderr)
                continue

        # Create tag (don't overwrite if it exists)
        tag_result = _git(repo_dir, "tag", tag)
        if tag_result.returncode != 0:
            print(
                f"[{repo_name}] tag {tag} already exists or failed: "
                f"{tag_result.stderr.strip()}",
                file=sys.stderr,
            )
            continue
        else:
            if cmake_changed:
                print(f"[{repo_name}] bumped {current or 'CMake version'} -> {version}, tagged {tag}")
            elif current == version:
                print(f"[{repo_name}] CMake already at {version}, tagged {tag}")
            else:
                print(f"[{repo_name}] tagged {tag} (no CMake version change)")

        # Push commit and tag to origin
        if push:
            push_result = _git(repo_dir, "push", "origin", "HEAD", tag)
            if push_result.returncode != 0:
                print(
                    f"[{repo_name}] push failed: "
                    f"{push_result.stderr.strip()}",
                    file=sys.stderr,
                )
            else:
                print(f"[{repo_name}] pushed {tag} to origin")

        processed += 1

    return processed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump version for SonicDE repos by category."
    )
    parser.add_argument(
        "category",
        choices=["plasma", "frameworks", "system"],
        help="Version category",
    )
    parser.add_argument("version", nargs="?", help="New version (X.Y.Z)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without modifying files",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Do not push commits and tags to origin (push is the default)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the maintained repository list and exit",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Project root (default: auto-detect from script location)",
    )

    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent

    try:
        _find_repos(root, args.category)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    if args.list:
        repos = _find_repos(root, args.category)
        for repo in repos:
            print(repo)
        return 0

    if not args.version:
        parser.error("version is required unless --list is given")

    if not _validate_version(args.version):
        parser.error(f"version must be in X.Y.Z format, got {args.version!r}")

    n = bump_category(
        root, args.category, args.version,
        dry_run=args.dry_run, push=not args.no_push,
    )
    print(f"\n[{args.category}] processed {n} repo(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
