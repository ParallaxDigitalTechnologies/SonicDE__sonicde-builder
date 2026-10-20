SonicDE standalone builder
==========================

This is a standalone builder for [SonicDE](https://github.com/Sonic-DE/)
(fork of KDE with full X11 compatibility) with a Python + CMake
superbuild pipeline.

Warning: it's still an early work-in-progress.

howto:
------

* install dependencies: `pip install pyyaml` and a working Qt6 + CMake 3.28+
* just fetch git repos: `./fetch-all`
* full build: `./build-all`
* create dependency graph: `./generate-depgraph`
* run upstream sync (autopick): `./sync`
* reset repos after merged PRs: `./sync-success-cleanup`
* cleanup failed autopick runs: `./sync-fail-cleanup --force`
* reset trackers (recovery): `./reset-trackers --yes`
* check for missing GitHub repos: `./check-new-repos`
* list OS packages to install: `./install-deps`
* preview stale Frameworks debug exports: `./cleanup-stale-cmake-debug`
* merge per-project graphify graphs: `./merge-graphs`
* bump Plasma version and tag: `./version-bump-plasma 6.7.6`
* bump Frameworks version and tag: `./version-bump-frameworks 6.31.0`
* bump System version and tag: `./version-bump-system 26.08.1`
* list repos in a category: `./version-bump-plasma --list`

stale debug CMake exports:
--------------------------

Old debug installations can leave `KF6*Targets-debug.cmake` fragments referring
to libraries that no longer exist. Preview them on the affected build host:

    ./cleanup-stale-cmake-debug

Remove confirmed stale fragments explicitly (elevate only when required):

    sudo ./cleanup-stale-cmake-debug --apply

Use `--prefix /opt/sonicde` or `--prefix state/install-stage/usr` to inspect
another installation; `--prefix` can be repeated. The default prefix is `/usr`.
The command does not hard-code a Frameworks version, execute CMake code, or
remove main config/target files. It removes a debug fragment when any file it
references is missing, without requiring a release or other replacement export.
Healthy debug exports are retained. Unsupported or unsafe fragments are
reported and retained. Run it between builds and
installations. It is not invoked automatically by `build-all`.

version bumps:
--------------

Three scripts release all repositories in three explicitly maintained lists:

* Plasma: `scripts/version-repos-plasma.list`
* Frameworks: `scripts/version-repos-frameworks.list`
* System: `scripts/version-repos-system.list`

The lists were populated from the latest SonicDE release tags in each
repository (`6.7.5[.patch]`, `6.30.0[.patch]`, and `26.08.0[.patch]`,
respectively). Repositories with different version schemes are excluded.
The scripts read these lists as-is; they do not discover repositories by
searching CMake files or tags at release time. Maintain the lists explicitly
when a repository joins or leaves a release group.

For each listed repository, the script performs these steps in order:

1. Update existing release-version fields in `CMakeLists.txt`, if present.
2. Commit the CMake change only if the file actually changed.
3. Create the `<version>` tag (without a `v` prefix), then push the commit
   and tag to `origin` unless `--no-push` is specified.

Repositories without a CMake file or matching release-version fields are
still tagged. If CMake is already at the requested version but the tag is
missing, the script creates the tag without an empty commit. Existing tags
are never overwritten; repositories already carrying the requested tag are
skipped. Unlike KDE's release scripts, no second "bump to next dev version"
commit is created -- we make patch releases against these tagged versions
(e.g. `6.7.4.1`).

    ./version-bump-plasma 6.7.6
    ./version-bump-frameworks 6.31.0
    ./version-bump-system 26.08.1

The version argument must be in `X.Y.Z` format. Use `--dry-run` to preview
CMake changes and tags without modifying files, commits, tags, or remotes:

    ./version-bump-plasma 6.7.6 --dry-run

Use `--list` to print the maintained list without modifying anything:

    ./version-bump-plasma --list
    ./version-bump-frameworks --list
    ./version-bump-system --list

The usual CMake edit patterns are `set(PROJECT_VERSION "X.Y.Z")` for
**Plasma**, `set(KF_VERSION "X.Y.Z")` for **Frameworks**, and the three
`set(RELEASE_SERVICE_VERSION_MAJOR/MINOR/MICRO "X")` variables for
**System**. Frameworks also updates `set(KF_DEP_VERSION "X.Y.Z")` and
literal `find_package(ECM X.Y.Z)` requirements when present. Plasma
supports a literal `project(... VERSION X.Y.Z)` declaration, and
`sonic-frameworks-cmake-modules` updates its existing `set(VERSION ...)`.
These are editing rules, not membership tests. Missing fields are not
invented; unrelated dependency and library ABI versions are left alone.

Each script requires a clean working tree in every repo it touches.
Repos with uncommitted tracked changes are skipped with a warning. Listed
repositories whose checkouts are missing are also reported and skipped;
they remain in the maintained release list.

build and system installation:
------------------------------

Build into the solution's local prefix (the default remains `build/`):

    ./build-all --parallel 8

The meta-build schedules one package at a time so nested Ninja processes cannot
multiply the requested concurrency. `--parallel N` controls compilation inside
that package. Without it, the builder chooses a conservative value from available
memory (roughly one job per 2 GiB after reserving 1 GiB, capped at eight). Set
`SONICDE_BUILD_JOBS=N` for a persistent override.

Build the full meta-build, then install its CMake packages to `/usr`:

    ./build-all --install --parallel 8

Select a different final destination with:

    ./build-all --install --install-prefix /opt/sonicde --parallel 8

With `--install`, packages are configured for the final destination, while every
dependency installation during the build is redirected with `DESTDIR` under
`state/install-stage/`. Later packages discover these staged dependencies.
**No live-system installation starts until the entire meta-build succeeds.**
If validation, configuration or any build fails, deployment is not run.
Partial-target builds are not accepted by this wrapper.

After the full build succeeds, the wrapper runs `sudo -v` to authenticate
(prompting for a password when required by sudo policy), then runs only the
installation helper under sudo. Cancelling or failing authentication prevents
deployment. Configuration and compilation are not elevated. If deployment
needs to be retried after a successful `--install` build, authenticate and run
the deployment-only step from the workspace:

    sudo -v
    sudo -- python3 scripts/install.py -model state/model.json

Use that helper only with the model from the completed system-prefix build. It
checks all package installation scripts and configured prefixes before starting,
skips system/no-build packages, and stops on the first deployment error.
Deployment is not transactional: an install failure can leave earlier packages
installed, although no packages are deployed while the meta-build is incomplete.

architecture:
-------------

The builder consists of Python scripts that parse the SonicDE solution
and package YAML, resolve the dependency closure, and generate a CMake
superbuild using `ExternalProject_Add`.

    scripts/config.py        parse YAML, resolve closure, emit model.json
    scripts/repositories.py  generate repository views and repo-list
    scripts/fetch.py         fetch Git repositories from manifest metadata
    scripts/validate.py      validate system dependencies and Qt6 Core
    scripts/generate.py      generate CMake ExternalProject superbuild
    scripts/install.py       deploy completed CMake packages after the full build
    scripts/git-autopick     upstream sync (rebase tracker range onto master)

configuration:
--------------

The `config/sonicde/` tree is imported from the SonicDE meta-build
workspace. The solution file (`config/sonicde/solutions/sonicde.yaml`) defines the
build list, install prefix, environment, and fetch refspecs. Package
manifests under `config/sonicde/packages/` define Git sources, dependencies, and
build systems.

Only CMake and no-build packages are supported. System packages are
validated via `pkg-config`. Qt6 is supplied by the operating system
and is deliberately not fetched or built.

tests:
------

Run the test suite with:

    python3 -m pytest tests/ -v

All tests use local Git repositories and fixture CMake projects. No
remote repositories are contacted.
