# SonicDE Standalone Builder

This is a standalone build orchestration project for
[SonicDE](https://github.com/Sonic-DE/) (fork of KDE with full X11
compatibility). It replaces the former MPBT workspace with a Python +
CMake superbuild pipeline.

## Directory Structure

```text
sonicde-builder-wip/
├── AGENTS.md
├── README.md
├── CMakeLists.txt                     # top-level superbuild (Qt6 probe + include)
├── sync                              # run upstream sync (autopick) for one repo argument
├── sync-all                          # run upstream sync (autopick) for all repos
├── sync-fail-cleanup                 # destructive recovery (--force required)
├── sync-success-cleanup              # reset repos to origin/master after PRs merge
├── sync-tags                         # mirror upstream release tags onto SonicDE commits
├── build-all                          # full build: config -> validate -> generate -> cmake
├── check-new-repos                    # compare GitHub org listing against managed repos
├── fetch                              # fetch one repository argument
├── fetch-all                          # fetch all active repositories through fetch
├── generate-depgraph                 # generate DOT dependency graph
├── install-deps                       # list OS packages needed by active system deps
├── merge-graphs                       # merge per-project graphify graphs into root graph
├── reset-trackers                     # reset autopick trackers (recovery, --yes required)
├── repo-list                          # generated compatibility artifact
├── config/
│   ├── repos.list                     # maintained SonicDE repository inventory
│   └── sonicde/
│       ├── solutions/sonicde.yaml     # active solution (build list, prefix, env, fetch)
│       └── packages/                  # package manifests (sonicde, 3rdparty, os-installed, qt6)
├── cmake/
│   └── SonicDEProjects.cmake         # generated ExternalProject definitions
├── scripts/
│   ├── config.py                      # parse YAML, resolve closure, emit model.json
│   ├── repositories.py                # generate repository views and repo-list
│   ├── fetch.py                       # fetch Git repositories from manifest metadata
│   ├── validate.py                    # validate system deps (pkg-config) and Qt6 Core
│   ├── generate.py                    # generate CMake ExternalProject superbuild + DOT
│   ├── sync_tags.py                   # mirror upstream tags onto SonicDE commits
│   └── git-autopick                   # upstream sync (rebase tracker range onto master)
├── src/
│   ├── 3rdparty/<project>/            # one independent Git repository per project
│   └── sonicde/<project>/             # one independent Git repository per project
├── build/                             # CMake build directory (generated)
├── state/
│   ├── model.json                     # normalized active closure model (generated)
│   ├── logs/                          # per-command and test logs
│   ├── failed-sync-repos.txt          # upstream sync failure list
│   ├── failed-sync-tag-repos.txt      # tag sync failure list
│   └── success-sync-tag-repos.txt     # successful tag sync list
└── tests/                             # Python unit tests (pytest/CTest)
    ├── fixtures/                      # shared local Git repo / CMake fixtures
    ├── test_config.py
    ├── test_config_comprehensive.py
    ├── test_fetch.py
    ├── test_fetch_comprehensive.py
    ├── test_superbuild.py
    ├── test_autopick.py
    ├── test_autopick_success_cleanup.py
    ├── test_sync_tags.py
    ├── test_panelview.py
    └── test_sonic_win_rename.py
```

## Context Protocol

### Worktree Policy

Never create Agent Manager worktrees or invoke `agent_manager` with
`mode: "worktree"`. Work only in the current checkout. This restriction
persists across sessions and may only be changed by an explicit user edit to
`kilo.json`.

1. This project is its own Git repository. Commit builder changes here;
   do not commit generated artifacts (`src/*/`, `build/`, `state/`,
   `cmake/`, `repo-list`, `depgraph.*`, `graphify-out/`).
2. Every immediate child of `src/3rdparty/` and `src/sonicde/` is a
   separate independent Git repository fetched by `fetch` or `fetch-all`. Run Git
   commands inside the specific project repository being changed, not
   from the project root.
3. The `config/sonicde/` tree is the imported build configuration. It is
   authoritative for package metadata, dependency resolution, and
   repository definitions. Do not edit it to work around a builder bug;
   fix the builder.
4. Do not modify `sonicde-meta-build` or its `_WORK_/` workspace. This
   project is the replacement, not a companion.
5. When a change crosses package boundaries, inspect every affected
   repository and verify dependency, API, and build-system alignment
   using `generate-depgraph` and `state/model.json`.

## Builder-Owned Dependency Chain

The builder builds the **entire SonicDE dependency chain, including all
Frameworks packages**. Do not treat SonicDE Frameworks as system-provided KDE
dependencies or assume a distribution's installed KF6 packages are acceptable
substitutes for the builder's own packages.

Every required SonicDE package must be represented in the consuming package's
manifest, so its build and staged installation finish before the consumer is
configured. Verify requirements against SonicDE's actual CMake sources and map
the CMake package names to the corresponding SonicDE repository names.

If CMake selects a system KF6 config instead of the staged SonicDE provider,
investigate missing dependency edges, build/install ordering, staged discovery,
and source/version alignment. Fix the verified cause in the builder or its
manifests; do not use installing distribution Frameworks packages as a substitute
for correcting the builder-owned chain.

Qt6 and dependencies explicitly declared under `os-installed/` remain supplied
by the operating system. They are distinct from builder-owned SonicDE packages.

## Adding or Renaming SonicDE Packages

Release version edits and tagging are separate: `version-bump-core`,
`version-bump-frameworks`, and `version-bump-system` only update/commit CMake
versions and push `master`. `version-bump-tag-core`,
`version-bump-tag-frameworks`, and `version-bump-tag-system` only tag the accepted
`origin/master` commit and push that specific tag. Never push all branches or
all tags. `version-bump-project-dep` remains dependency-only and never tags.

When adding a SonicDE repository/package, update **all applicable maintained
lists in the same change**, not just its package manifest:

1. **`config/repos.list`** — add the repository basename, e.g.
   `sonic-power-management`.
2. **`config/sonicde/solutions/sonicde.yaml`** — add the package to `build`,
   using its full name, e.g. `sonicde/sonic-power-management`.
3. **The matching release list**, when the package belongs to a release group:
   - Core: `scripts/version-repos-plasma.list` (the legacy filename is retained).
   - Frameworks: `scripts/version-repos-frameworks.list`.
   - System: `scripts/version-repos-system.list`.

Also add its manifest under `config/sonicde/packages/sonicde/`. Use the current
canonical repository name consistently. For renames, replace the old name in
every affected list and rename/update the manifest; do not leave stale entries
or add duplicates.

The root **`repo-list` is generated**, not a substitute for either maintained
list under `config/`. Regenerating it alone does not register a new package.
Before reporting the work complete, explicitly verify membership in both
`config/repos.list` and `config/sonicde/solutions/sonicde.yaml`, plus the
applicable release list.

## Build Pipeline

The builder operates in distinct phases, each implemented as a Python
module invoked by the root command scripts:

1. **Config** (`scripts/config.py`): Parse the solution and package YAML,
   interpolate `${...}` variables, resolve the active dependency closure
   (exact names then unique `provides`), detect cycles, and write
   `state/model.json` atomically.
2. **Validate** (`scripts/validate.py`): Run `pkg-config --modversion`
   for every active system package and configure a real C++ CMake probe
   for `find_package(Qt6 REQUIRED COMPONENTS Core)`.
3. **Fetch** (`scripts/fetch.py`): Clone or update Git repositories from
   manifest metadata. Existing checkouts are updated without mutating
   HEAD, branch, index, or untracked files.
4. **Generate** (`scripts/generate.py`): Emit `cmake/SonicDEProjects.cmake`
   with `ExternalProject_Add` targets and `DEPENDS` edges from the
   resolved closure.
5. **Build** (`build-all`): Configure the parent CMake project and build
   the requested targets.

## Autopick

`scripts/git-autopick` synchronizes forked repositories with their
upstream sources. It is run for one named repository by `sync` and for all
managed repositories by `sync-all`.

Key invariants:

- The tracker records an upstream commit that has been processed. It
  always remains on upstream history and is never replaced by a rebased
  commit identity.
- The temporary sync branch starts from upstream and rebases the
  tracker-to-upstream work onto master.
- If the rebased branch has the same commit as master, no PR is created;
  the temporary branch is removed and the tracker advances.
- Existing remote sync branches are checked before starting new work so
  an open or unmerged sync branch is not duplicated.

`sync-tags` (via `scripts/sync_tags.py`) is a separate flow: it mirrors
each upstream's latest release tag onto the patch-equivalent SonicDE
commit. It does not create PRs. Results land in
`state/{failed,success}-sync-tag-repos.txt`.

## Testing

Run the full test suite:

```bash
python3 -m pytest tests/ -v
```

All tests use local Git repositories, fixture CMake projects, fake
`pkg-config`, and fake `gh`. No remote repositories are contacted.

When adding new features or fixing bugs, add a test that covers the
specific scenario. The test baseline (captured `pytest -v` output) can
be regenerated into `state/logs/test-baseline.log`; it is a local-only
artifact, gitignored along with the rest of `state/`.

## Graphify

When the user invokes `/graphify`, load and follow the installed
Graphify skill before doing anything else.

Rules:

- For codebase questions about checked-out source repositories under
  `src/`, run `graphify query "<question>"` from the specific project
  directory under `src/<group>/<project>/`.
- The builder's own `scripts/` and `tests/` are small enough to explore
  directly; Graphify is not required for builder-internal questions.
- After changing source code in a checked-out repository, run
  `graphify update .` inside that project directory.
- Do not run Graphify from the project root expecting nested
  repositories under `src/` to be discovered automatically. `detect()`
  prunes `graphify-out/` at any depth and honors `.gitignore` (which
  ignores `src/*/`), so a bare `/graphify .` at the root graphs the
  builder only — never the SonicDE sub-projects.
- The root `./merge-graphs` wrapper composes the per-project graphs into
  the merged cross-repo graph at `graphify-out/graph.json`. It globs
  `src/sonicde/*/graphify-out/graph.json` and
  `src/3rdparty/*/graphify-out/graph.json`, requires at least two graphs,
  and prefixes node IDs per repo so same-named symbols across sub-projects
  do not collide. This is a full rebuild, not incremental.
  The user runs this command; agents must not run it automatically.
- For cross-repo or whole-SonicDE questions, run `graphify query
  "<question>"` at the project root against the merged
  `graphify-out/graph.json`. If it is missing or stale, report that to the
  user rather than running `merge-graphs`.

## Conventions

- Only CMake and no-build source packages are supported. Meson and other
  build systems are rejected during closure validation.
- Qt6 is supplied by the operating system and is deliberately not fetched
  or built. Active `qt6/*` source dependencies are rejected.
- Binary-package images and tarballs are not implemented.
- The `repo-list` file is a generated compatibility artifact, not
  authoritative. Repository views derive from the normalized model.
- Root command names:
  `sync`, `sync-all`, `sync-fail-cleanup`, `sync-success-cleanup`, `sync-tags`,
   `build-all`, `check-new-repos`, `fetch`, `fetch-all`, `generate-depgraph`,
  `install-deps`, `merge-graphs`, `reset-trackers`.
