#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Test configuration parsing, closure resolution, and validation."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from config import Project, ConfigError
from repositories import (active_git, managed_sonicde, autopick_repos,
                          post_autopick_repos, generate_repo_list, org_repo_names)


PLASMA_67_REPOSITORIES = {
    "sonic-power-management": "powerdevil",
    "sonic-print-management": "print-manager",
    "sonic-silver-sound-theme": "ocean-sound-theme",
}

NEW_PLASMA_REPOSITORIES = {
    **PLASMA_67_REPOSITORIES,
    "sonic-theme-sdk": "plasma-sdk",
}


class TestPublicRepositoryUrls(unittest.TestCase):
    def test_shipped_github_remotes_use_anonymous_https(self):
        """All manifests, including optional packages, must clone without SSH keys."""
        root = Path(__file__).resolve().parent.parent
        project = Project(root, root / "config/sonicde/solutions/sonicde.yaml")
        project.load()
        self.assertEqual(project.solution["sonicde_git"], "https://github.com/Sonic-DE")
        self.assertEqual(project.solution["ossqm_git"], "https://github.com/oss-qm")
        github_remotes = 0
        for name, package in project.packages.items():
            if not package.git:
                continue
            for remote_name, remote in package.git.remotes.items():
                with self.subTest(package=name, remote=remote_name):
                    self.assertFalse(remote.url.startswith(("git@", "ssh://")), remote.url)
                    if "github.com" in remote.url:
                        github_remotes += 1
                        self.assertTrue(remote.url.startswith("https://github.com/"), remote.url)
        self.assertGreater(github_remotes, 0)

    def test_ui_components_declares_direct_kio_dependency(self):
        root = Path(__file__).resolve().parent.parent
        project = Project(root, root / "config/sonicde/solutions/sonicde.yaml")
        project.load()
        package = project.packages["sonicde/sonic-frameworks-ui-components"]
        self.assertIn("sonicde/sonic-frameworks-io", package.depends)


class TestPlasmaSyncBranches(unittest.TestCase):
    def test_unmaintained_upstreams_are_standalone_but_still_plasma_releases(self):
        root = Path(__file__).resolve().parent.parent
        project = Project(root, root / "config/sonicde/solutions/sonicde.yaml")
        project.load()
        closure = project.build_closure()
        roster = set((root / "scripts/version-repos-plasma.list").read_text().splitlines())
        for name in ("sonic-drawing-tablet", "sonic-gamma", "sonic-win"):
            with self.subTest(repository=name):
                package = project.packages[f"sonicde/{name}"]
                self.assertEqual(str(package.git.config["autopick.enabled"]).lower(), "false")
                self.assertEqual(set(package.git.remotes), {"origin"})
                self.assertNotIn("autopick.upstream", package.git.config)
                self.assertNotIn("autopick.tracker", package.git.config)
                self.assertIn(f"sonicde/{name}", closure.packages)
                self.assertIn(name, roster)

    def test_rdp_manifest_matches_release_repository_without_restoring_retired_library(self):
        root = Path(__file__).resolve().parent.parent
        project = Project(root, root / "config/sonicde/solutions/sonicde.yaml")
        project.load()
        rdp = project.packages["sonicde/sonic-rdp-server"]
        self.assertTrue(rdp.git.remotes["origin"].url.endswith("/sonic-rdp-server.git"))
        self.assertEqual(project.resolve_name("sonicde/sonic-rdp"), "sonicde/sonic-rdp-server")
        self.assertNotIn("sonicde/sonic-plasma5-support-library", project.packages)
        self.assertNotIn("sonicde/sonic-plasma5-support-library", project.build_closure().packages)

    def test_shipped_plasma_branches_and_trackers_use_configured_release(self):
        """Check optional manifests as well as the normalized active closure."""
        root = Path(__file__).resolve().parent.parent
        project = Project(root, root / "config/sonicde/solutions/sonicde.yaml")
        project.load()
        plasma_packages = set()
        for name, package in project.packages.items():
            if not package.git:
                continue
            config = package.git.config
            upstream = config.get("autopick.upstream", "")
            tracker = config.get("autopick.tracker", "")
            if upstream.startswith("upstream/Plasma/") or tracker.startswith("origin/tracking/plasma-"):
                plasma_packages.add(name)
                branch = "6.7" if name.split("/")[-1] in PLASMA_67_REPOSITORIES else "6.8"
                with self.subTest(package=name):
                    self.assertEqual(upstream, f"upstream/Plasma/{branch}")
                    self.assertEqual(tracker, f"origin/tracking/plasma-{branch}")
        self.assertTrue(plasma_packages)

        model = project.to_model(project.build_closure())
        for name in plasma_packages & model["packages"].keys():
            config = model["packages"][name]["git"]["config"]
            branch = "6.7" if name.split("/")[-1] in PLASMA_67_REPOSITORIES else "6.8"
            with self.subTest(model_package=name):
                self.assertEqual(config["autopick.upstream"], f"upstream/Plasma/{branch}")
                self.assertEqual(config["autopick.tracker"], f"origin/tracking/plasma-{branch}")

    def test_new_plasma_repositories_are_in_all_applicable_lists(self):
        root = Path(__file__).resolve().parent.parent
        project = Project(root, root / "config/sonicde/solutions/sonicde.yaml")
        project.load()
        model = project.to_model(project.build_closure())
        roster = (root / "scripts/version-repos-plasma.list").read_text().splitlines()
        for name, upstream in NEW_PLASMA_REPOSITORIES.items():
            key = f"sonicde/{name}"
            branch = "6.7" if name in PLASMA_67_REPOSITORIES else "6.8"
            with self.subTest(repository=name):
                self.assertEqual(project.solution["build"].count(key), 1)
                self.assertEqual(roster.count(name), 1)
                package = model["packages"][key]
                self.assertEqual(package["buildsystem"], "cmake")
                git = package["git"]
                self.assertEqual(git["ref"], "origin/master")
                self.assertEqual(git["local_branch"], "master")
                self.assertEqual(git["remotes"]["origin"]["url"], f"https://github.com/Sonic-DE/{name}.git")
                self.assertEqual(git["remotes"]["upstream"]["url"], f"https://invent.kde.org/plasma/{upstream}.git")
                self.assertEqual(git["config"]["autopick.upstream"], f"upstream/Plasma/{branch}")
                self.assertEqual(git["config"]["autopick.tracker"], f"origin/tracking/plasma-{branch}")
                for view in (active_git, managed_sonicde, autopick_repos, post_autopick_repos):
                    self.assertIn(key, view(model), view.__name__)
                self.assertEqual(generate_repo_list(model).count(name), 1)
                self.assertEqual(org_repo_names(model).count(name), 1)


class TestConfigParsing(unittest.TestCase):
    """Test YAML parsing, interpolation, and closure resolution."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_solution(self, packages_dir: Path, **extra) -> Path:
        sol = {
            "install-prefix": str(self.root / "prefix"),
            "build": [],
            "packages": [str(packages_dir)],
            "package-defaults": {},
        }
        sol.update(extra)
        sol_path = self.root / "solution.yaml"
        sol_path.write_text(
            __import__("yaml").safe_dump(sol, default_flow_style=False))
        return sol_path

    def _make_pkg(self, packages_dir: Path, name: str, **fields) -> Path:
        ns, _, basename = name.partition("/")
        pkg_dir = packages_dir / ns
        pkg_dir.mkdir(parents=True, exist_ok=True)
        pkg_file = pkg_dir / f"{basename}.yaml"
        pkg_file.write_text(
            __import__("yaml").safe_dump(fields, default_flow_style=False))
        return pkg_file

    def test_exact_package_resolution(self):
        """Exact package identity is resolved first."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/foo", buildsystem="cmake")
        sol = self._make_solution(pdir, build=["sonicde/foo"])
        prj = Project(self.root, sol)
        prj.load()
        cl = prj.build_closure()
        self.assertIn("sonicde/foo", cl.packages)

    def test_python_modules_are_serialized_for_validation(self):
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "os-installed/python-backend", type="system",
                       **{"python-modules": ["setuptools.build_meta", "wheel"],
                          "commands": ["sassc"],
                          "headers": ["boost/version.hpp"],
                          "cmake-packages": ["Qt6Keychain"],
                          "cmake-packages-any": ["OpenCV 5", "OpenCV 4.7"],
                          "platform-packages": {"arch": "python-setuptools", "debian": "python3-setuptools"}})
        sol = self._make_solution(pdir, build=["os-installed/python-backend"])
        project = Project(self.root, sol)
        project.load()
        closure = project.build_closure()
        model = project.to_model(closure)
        self.assertEqual(model["packages"]["os-installed/python-backend"]["python_modules"],
                         ["setuptools.build_meta", "wheel"])
        self.assertEqual(model["packages"]["os-installed/python-backend"]["platform_packages"]["arch"],
                         "python-setuptools")
        self.assertEqual(model["packages"]["os-installed/python-backend"]["commands"], ["sassc"])
        self.assertEqual(model["packages"]["os-installed/python-backend"]["headers"], ["boost/version.hpp"])
        self.assertEqual(model["packages"]["os-installed/python-backend"]["cmake_packages"], ["Qt6Keychain"])
        self.assertEqual(model["packages"]["os-installed/python-backend"]["cmake_packages_any"],
                         ["OpenCV 5", "OpenCV 4.7"])

    def test_provides_resolution(self):
        """Unique provides entry resolves when no exact match."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "os-installed/foo",
                       provides="sys/foo", type="system",
                       **{"pkg-config": "foo"})
        sol = self._make_solution(pdir, build=["sys/foo"])
        prj = Project(self.root, sol)
        prj.load()
        cl = prj.build_closure()
        self.assertIn("os-installed/foo", cl.packages)

    def test_ambiguous_provider_fails(self):
        """Ambiguous provider raises an error."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "a/foo", provides="sys/foo", type="system")
        self._make_pkg(pdir, "b/foo", provides="sys/foo", type="system")
        sol = self._make_solution(pdir, build=["sys/foo"])
        prj = Project(self.root, sol)
        prj.load()
        with self.assertRaises(ConfigError) as ctx:
            prj.build_closure()
        self.assertIn("ambiguous", str(ctx.exception))

    def test_missing_dependency_fails(self):
        """Missing dependency raises an error."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/foo",
                       buildsystem="cmake",
                       depends=["sonicde/nonexistent"])
        sol = self._make_solution(pdir, build=["sonicde/foo"])
        prj = Project(self.root, sol)
        prj.load()
        with self.assertRaises(ConfigError):
            prj.build_closure()

    def test_cycle_detection(self):
        """Dependency cycles are detected and reported."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/a",
                       buildsystem="cmake", depends=["sonicde/b"])
        self._make_pkg(pdir, "sonicde/b",
                       buildsystem="cmake", depends=["sonicde/a"])
        sol = self._make_solution(pdir, build=["sonicde/a"])
        prj = Project(self.root, sol)
        prj.load()
        with self.assertRaises(ConfigError) as ctx:
            prj.build_closure()
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_qt6_source_rejected(self):
        """Active qt6/* source packages are rejected."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "qt6/qtbase",
                       buildsystem="cmake",
                       **{"sources": {"git": {
                           "url": "https://example.com/qtbase.git",
                           "ref": "v6.7.0"}}})
        sol = self._make_solution(pdir, build=["qt6/qtbase"])
        prj = Project(self.root, sol)
        prj.load()
        with self.assertRaises(ConfigError) as ctx:
            prj.build_closure()
        self.assertIn("Qt source", str(ctx.exception))

    def test_unsupported_buildsystem_rejected(self):
        """Active unsupported build systems are rejected."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/foo",
                       buildsystem="meson",
                       **{"sources": {"git": {
                           "url": "https://example.com/foo.git",
                           "ref": "master"}}})
        sol = self._make_solution(pdir, build=["sonicde/foo"])
        prj = Project(self.root, sol)
        prj.load()
        with self.assertRaises(ConfigError) as ctx:
            prj.build_closure()
        self.assertIn("unsupported buildsystem", str(ctx.exception))

    def test_interpolation_basename(self):
        """${@basename} is interpolated correctly."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/myrepo",
                       buildsystem="cmake",
                       master_branch="master",
                       **{"sources": {"git": {
                           "ref": "origin/${master_branch}",
                           "remotes": {"origin": {
                               "url": "https://example.com/${@basename}.git",
                               "fetch": ["refs/heads/*:refs/remotes/origin/*"],
                           }}}}})
        sol = self._make_solution(pdir, build=["sonicde/myrepo"])
        prj = Project(self.root, sol)
        prj.load()
        cl = prj.build_closure()
        pkg = cl.packages["sonicde/myrepo"]
        self.assertEqual(pkg.git.remotes["origin"].url,
                         "https://example.com/myrepo.git")
        self.assertEqual(pkg.git.ref, "origin/master")

    def test_interpolation_solution_nested_list(self):
        """${@SOLUTION::fetch::origin} resolves to a list, not a string."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/myrepo",
                       buildsystem="cmake",
                       master_branch="master",
                       **{"sources": {"git": {
                           "ref": "origin/${master_branch}",
                           "remotes": {"origin": {
                               "url": "https://example.com/${@basename}.git",
                               "fetch": "${@SOLUTION::fetch::origin}",
                           }}}}})
        sol = self._make_solution(
            pdir,
            build=["sonicde/myrepo"],
            **{"fetch": {"origin": [
                "refs/heads/*:refs/remotes/origin/*",
                "refs/tags/*:refs/tags/origin/*",
            ]}})
        prj = Project(self.root, sol)
        prj.load()
        cl = prj.build_closure()
        pkg = cl.packages["sonicde/myrepo"]
        self.assertEqual(pkg.git.remotes["origin"].fetch,
                         ["refs/heads/*:refs/remotes/origin/*",
                          "refs/tags/*:refs/tags/origin/*"])

    def test_package_mapping(self):
        """Explicit package-mapping is applied before exact/provider lookup."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "os-installed/libdrm",
                       provides="sys/libdrm", type="system",
                       **{"pkg-config": "libdrm"})
        self._make_pkg(pdir, "sonicde/foo",
                       buildsystem="cmake",
                       depends=["sys/libdrm"])
        sol = self._make_solution(
            pdir,
            build=["sonicde/foo"],
            **{"package-mapping": {"sys/libdrm": "os-installed/libdrm"}})
        prj = Project(self.root, sol)
        prj.load()
        cl = prj.build_closure()
        self.assertIn("os-installed/libdrm", cl.packages)

    def test_model_serialization(self):
        """Model JSON is written atomically."""
        pdir = self.root / "pkgs"
        self._make_pkg(pdir, "sonicde/foo", buildsystem="cmake")
        sol = self._make_solution(pdir, build=["sonicde/foo"])
        prj = Project(self.root, sol)
        prj.load()
        cl = prj.build_closure()
        out = self.root / "model.json"
        prj.write_model(cl, out)
        model = json.loads(out.read_text())
        self.assertEqual(model["schema_version"], 1)
        self.assertIn("sonicde/foo", model["packages"])


if __name__ == "__main__":
    unittest.main()
