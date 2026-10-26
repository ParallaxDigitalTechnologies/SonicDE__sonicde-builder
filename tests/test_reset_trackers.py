#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise selective tracker resets against local remotes only."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

SOURCE = Path(__file__).resolve().parent.parent

# Fixture releases, independent of the release the solution currently tracks:
# manifests declare CURRENT while each checkout's stale git config still points
# at PREVIOUS, whose tracker must never be touched by a CURRENT reset.
CURRENT = "9.1"
PREVIOUS = "9.0"


def tracker_ref(release):
    return f"refs/heads/tracking/plasma-{release}"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()

class TestResetTrackers(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(SOURCE / "reset-trackers", self.root / "reset-trackers")
        for script in ("config.py", "repositories.py", "version_bump.py"):
            shutil.copy2(SOURCE / "scripts" / script, self.root / "scripts" / script)
        for category in ("plasma", "frameworks", "system"):
            (self.root / "scripts" / f"version-repos-{category}.list").write_text("")
        self.packages = self.root / "config/sonicde/packages/sonicde"
        self.packages.mkdir(parents=True)
        self.solution = self.root / "config/sonicde/solutions/sonicde.yaml"
        self.solution.parent.mkdir(parents=True)
        self.names = []

    def tearDown(self):
        self.temp.cleanup()

    def make_repo(self, name, category):
        upstream = self.root / f"upstream-{name}"
        upstream.mkdir()
        git(upstream, "init", "-b", "master")
        git(upstream, "config", "user.name", "Test")
        git(upstream, "config", "user.email", "test@example.invalid")
        (upstream / "base").write_text("shared history\n")
        git(upstream, "add", "base")
        git(upstream, "commit", "-m", "base")
        base = git(upstream, "rev-parse", "HEAD")
        git(upstream, "update-ref", f"refs/heads/Plasma/{CURRENT}", base)
        git(upstream, "symbolic-ref", "HEAD", f"refs/heads/Plasma/{CURRENT}")
        (upstream / "synced").write_text("already imported\n")
        git(upstream, "add", "synced")
        git(upstream, "commit", "-m", "upstream synced change")
        synced = git(upstream, "rev-parse", "HEAD")
        git(upstream, "update-ref", f"refs/heads/Plasma/{PREVIOUS}", synced)
        (upstream / "pending").write_text("not imported\n")
        git(upstream, "add", "pending")
        git(upstream, "commit", "-m", "upstream pending change")
        tip = git(upstream, "rev-parse", "HEAD")

        repo = self.root / "src/sonicde" / name
        repo.parent.mkdir(parents=True, exist_ok=True)
        git(self.root, "clone", "--branch", "master", str(upstream), str(repo))
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "user.email", "test@example.invalid")
        (repo / "fork").write_text("fork changes\n")
        git(repo, "add", "fork")
        git(repo, "commit", "-m", "fork customization")
        git(repo, "cherry-pick", synced)
        self.assertNotEqual(git(repo, "rev-parse", "HEAD"), synced)
        origin = self.root / f"origin-{name}.git"
        git(self.root, "clone", "--bare", str(repo), str(origin))
        git(repo, "remote", "rename", "origin", "upstream")
        git(repo, "remote", "add", "origin", str(origin))
        git(repo, "fetch", "origin")
        git(repo, "config", "autopick.tracker", f"origin/tracking/plasma-{PREVIOUS}")
        git(repo, "config", "autopick.enabled", "true")
        git(repo, "config", "autopick.master", "origin/master")
        git(repo, "config", "autopick.upstream", f"upstream/Plasma/{PREVIOUS}")
        git(origin, "update-ref", tracker_ref(PREVIOUS), base)
        git(origin, "update-ref", tracker_ref(CURRENT), tip)

        config = {
            "autopick.enabled": "true",
            "autopick.tracker": f"origin/tracking/plasma-{CURRENT}",
            "autopick.master": "origin/master",
            "autopick.upstream": f"upstream/Plasma/{CURRENT}",
        }
        manifest = {
            "buildsystem": "cmake",
            "sources": {"git": {
                "ref": "origin/master",
                "remotes": {"origin": {"url": str(origin)}, "upstream": {"url": str(upstream)}},
                "config": config,
            }},
        }
        (self.packages / f"{name}.yaml").write_text(yaml.safe_dump(manifest))
        self.names.append(f"sonicde/{name}")
        self.solution.write_text(yaml.safe_dump({
            "install-prefix": str(self.root / "build"),
            "packages": [str(self.packages.parent)],
            "build": self.names,
        }))
        roster = self.root / "scripts" / f"version-repos-{category}.list"
        roster.write_text(roster.read_text() + name + "\n")
        return repo, origin, base, synced, tip

    def run_reset(self, *args):
        return subprocess.run([str(self.root / "reset-trackers"), *args],
                              cwd=self.root, capture_output=True, text=True)

    def test_selective_reset_uses_declared_release_and_preserves_other_category(self):
        repo, origin, base, synced, tip = self.make_repo("sonic-plasma", "plasma")
        _, other_origin, _, _, other_tip = self.make_repo("sonic-framework", "frameworks")
        head = git(repo, "rev-parse", "HEAD")
        (repo / "fork").write_text("uncommitted local edits\n")
        (repo / "untracked").write_text("local file\n")
        status = git(repo, "status", "--porcelain")
        result = self.run_reset("--category", "plasma", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("patch-equivalent commit", result.stdout)
        self.assertIn("tracker verified", result.stdout)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), synced)
        self.assertNotEqual(synced, tip)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(PREVIOUS)), base)
        self.assertEqual(git(other_origin, "rev-parse", tracker_ref(CURRENT)), other_tip)
        self.assertEqual(git(repo, "rev-parse", "HEAD"), head)
        self.assertEqual(git(repo, "status", "--porcelain"), status)
        self.assertEqual(git(repo, "config", "autopick.upstream"), f"upstream/Plasma/{PREVIOUS}")

    def test_selective_preview_does_not_change_tracker(self):
        _, origin, _, synced, tip = self.make_repo("sonic-plasma", "plasma")
        result = self.run_reset("--category", "plasma")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(synced, result.stdout)
        self.assertIn("dry run", result.stdout)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), tip)

    def test_without_category_keeps_using_checkout_config(self):
        _, origin, _, synced, tip = self.make_repo("sonic-plasma", "plasma")
        result = self.run_reset("--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(PREVIOUS)), synced)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), tip)

    def test_missing_upstream_branch_is_reported_without_reset(self):
        _, origin, _, _, tip = self.make_repo("sonic-plasma", "plasma")
        upstream = self.root / "upstream-sonic-plasma"
        git(upstream, "update-ref", "-d", f"refs/heads/Plasma/{CURRENT}")
        result = self.run_reset("--category", "plasma", "--yes")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("cant resolve upstream", result.stdout)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), tip)

    def test_merge_base_fallback_and_repeat_reset(self):
        _, origin, base, _, _ = self.make_repo("sonic-plasma", "plasma")
        git(origin, "update-ref", "refs/heads/master", base)
        result = self.run_reset("--category", "plasma", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("merge-base (no patch-equivalent commit found)", result.stdout)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), base)
        again = self.run_reset("--category", "plasma", "--yes")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("Updated: 0; unchanged: 1; failed: 0", again.stdout)

    def test_invalid_arguments_are_rejected(self):
        for args in (("--category",), ("--category", "unknown"), ("--typo",),
                     ("--repo",), ("--upstream-branch",), ("--repo", "sonic-a"),
                     ("--upstream-branch", f"Plasma/{CURRENT}")):
            with self.subTest(args=args):
                self.assertEqual(self.run_reset(*args).returncode, 2)

    def test_explicit_repo_filter_changes_only_requested_repo(self):
        _, selected_origin, _, selected_synced, _ = self.make_repo("sonic-selected", "plasma")
        _, other_origin, _, _, other_tip = self.make_repo("sonic-other", "plasma")
        result = self.run_reset("--category", "plasma", "--repo", "sonic-selected", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(selected_origin, "rev-parse", tracker_ref(CURRENT)), selected_synced)
        self.assertEqual(git(other_origin, "rev-parse", tracker_ref(CURRENT)), other_tip)

    def test_legacy_release_repo_can_reset_without_restoring_build_package(self):
        repo, origin, base, synced, _ = self.make_repo("sonic-legacy", "plasma")
        (self.packages / "sonic-legacy.yaml").unlink()
        solution = yaml.safe_load(self.solution.read_text())
        solution["build"] = []
        self.solution.write_text(yaml.safe_dump(solution))
        result = self.run_reset("--category", "plasma", "--repo", "sonic-legacy",
                                "--upstream-branch", f"Plasma/{CURRENT}", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("using existing checkout configuration", result.stderr)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), synced)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(PREVIOUS)), base)
        self.assertEqual(git(repo, "config", "autopick.upstream"), f"upstream/Plasma/{PREVIOUS}")
        self.assertFalse((self.packages / "sonic-legacy.yaml").exists())

    def test_legacy_repo_without_explicit_branch_is_not_reset(self):
        _, origin, _, _, tip = self.make_repo("sonic-legacy", "plasma")
        (self.packages / "sonic-legacy.yaml").unlink()
        solution = yaml.safe_load(self.solution.read_text())
        solution["build"] = []
        self.solution.write_text(yaml.safe_dump(solution))
        result = self.run_reset("--category", "plasma", "--repo", "sonic-legacy", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no matching package manifest", result.stderr)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), tip)

    def test_repo_not_in_release_list_is_rejected(self):
        _, origin, _, _, tip = self.make_repo("sonic-plasma", "plasma")
        result = self.run_reset("--category", "plasma", "--repo", "sonic-unlisted", "--yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Not in the plasma release list", result.stderr)
        self.assertEqual(git(origin, "rev-parse", tracker_ref(CURRENT)), tip)

if __name__ == "__main__":
    unittest.main()
