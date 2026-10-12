# Feasibility Study: Eliminating `sonic-pyside`


## Executive summary

The affected SonicDE Frameworks already use Qt directly for their native C++
libraries. Their `sonic-pyside` dependency exists specifically to generate and
run optional Python bindings. Removing those bindings removes the need for
PySide6 and Shiboken6; the native framework libraries continue using Qt
directly. The remaining Python test and build utilities must be ported to native
QML/C++ Qt equivalents.

## Project decision

SonicDE intends to eliminate PySide and Shiboken completely, not replace the
in-tree build with an external copy. Consequently, removing the generated
Python bindings is required.

## Required changes at a glance

Eliminating the `sonic-pyside` repository requires the following coordinated
changes. The later sections describe each workstream in detail.

1. **Remove the typesystem-based Python bindings from the eight affected
   Frameworks.** These bindings are the reason the Frameworks explicitly depend
   on PySide6 and Shiboken6. Their native C++ libraries already use Qt directly,
   so the bindings should be removed rather than replaced.
2. **Replace the PySide-based Appium fixtures with native QML/C++ tests.** The
   affected clipboard, notification, and system-tray tests directly import
   PySide6 and generated Frameworks Python modules. Native fixtures preserve the
   behavioral coverage without retaining a Python-to-Qt binding runtime.
3. **Replace the Breeze and Silver cursor generators and hotspot tests with a
   native `Qt6::Svg` utility.** These build tools directly import
   `PySide6.QtSvg.QSvgRenderer`; using `QSvgRenderer` from C++ removes their
   final runtime need for PySide.
4. **Remove the Python examples for the discontinued bindings.** They exercise
   Python modules that will no longer be produced and are not required by the
   native libraries. Native examples only need to be added where separate
   example coverage is desired.
5. **Remove the ECM Python-binding generator support.** Once the Frameworks
   bindings are gone, `ECMGeneratePythonBindings`, its wheel template, and its
   documentation have no remaining SonicDE consumers.
6. **Remove `sonic-pyside` and binding-only Python packaging dependencies from
   the builder configuration.** This includes the solution entry, package
   manifest, eight dependency edges, and the Python wheel tooling used solely
   for these bindings.
7. **Remove binding-specific CI and packaging paths.** Jobs that generate,
   build, install, package, or test the removed Python modules must be deleted or
   converted to validate the new native test and cursor utilities.

## Repositories with an explicit dependency

Eight package manifests explicitly list `sonicde/sonic-pyside` as a build
dependency:

1. `sonic-frameworks-core-addons`
2. `sonic-frameworks-gui-addons`
3. `sonic-frameworks-notifications`
4. `sonic-frameworks-progress-ui`
5. `sonic-frameworks-status-notification`
6. `sonic-frameworks-unit-conversion`
7. `sonic-frameworks-widgets-addons`
8. `sonic-frameworks-xml-gui`

In each repository, `BUILD_PYTHON_BINDINGS` defaults to `ON` on supported
desktop Unix platforms. When enabled, the build performs the following steps:

- Finds Python development files.
- Finds Shiboken6.
- Finds PySide6.
- Includes `ECMGeneratePythonBindings`.
- Runs `ecm_generate_python_bindings()` for the framework's public C++ API.

Representative locations include:

- `src/sonicde/sonic-frameworks-core-addons/CMakeLists.txt:100-110`
- `src/sonicde/sonic-frameworks-core-addons/python/CMakeLists.txt:59-74`
- `src/sonicde/sonic-frameworks-gui-addons/CMakeLists.txt:82-92`
- `src/sonicde/sonic-frameworks-notifications/CMakeLists.txt:90-100`
- `src/sonicde/sonic-frameworks-progress-ui/CMakeLists.txt:74-84`
- `src/sonicde/sonic-frameworks-status-notification/CMakeLists.txt:77-87`
- `src/sonicde/sonic-frameworks-unit-conversion/CMakeLists.txt:29-39`
- `src/sonicde/sonic-frameworks-widgets-addons/CMakeLists.txt:26-36`
- `src/sonicde/sonic-frameworks-xml-gui/CMakeLists.txt:80-90`

## How removing the Python bindings eliminates the dependency

The native framework libraries already link to Qt and do not need PySide. The
dependency is isolated to the optional CPython extension modules. The shared
ECM implementation in
`sonic-frameworks-cmake-modules/modules/ECMGeneratePythonBindings.cmake`:

- invokes the `shiboken6` generator;
- consumes PySide Qt typesystem descriptions;
- links generated modules to `PySide6::pyside6`;
- links generated modules to `Shiboken6::libshiboken`;
- includes PySide and Shiboken headers; and
- packages the result as Python wheels/modules.

The framework typesystems also explicitly load PySide's descriptions of Qt
types. Examples include:

- `typesystem_core.xml`
- `typesystem_gui.xml`
- `typesystem_widgets.xml`
- the generated `typesystem_kcoreaddons.xml`

These descriptions exist only to expose Qt and framework objects to Python.
Once the Python modules, their generator inputs, and their examples are removed,
none of this conversion infrastructure is needed. Native C++ and QML consumers
continue to use `Qt6::Core`, `Qt6::Gui`, `Qt6::Widgets`, and the other Qt
libraries directly.

## Binding removal order

The removable bindings are coupled to PySide at both build time and runtime:

- Core Addons loads the QtCore typesystem.
- GUI Addons loads QtCore and QtGui typesystems.
- Notifications loads the QtGui typesystem.
- Progress UI loads QtCore, QtWidgets, and KCoreAddons typesystems.
- Status Notification loads QtCore, QtGui, and QtWidgets typesystems.
- Unit Conversion loads the QtCore typesystem.
- Widgets Addons loads the QtWidgets typesystem.
- XML GUI loads the QtWidgets typesystem.

Progress UI additionally consumes the generated KCoreAddons typesystem. The
complete Python-binding layer should therefore be removed as one coordinated
change, or in dependency order with Progress UI removed before Core Addons.

## Other direct PySide6 users

Some repositories import PySide6 without declaring a direct `sonic-pyside`
package dependency.

### `sonic-workspace`

Several Appium test fixtures use PySide6, including helpers for:

- notifications;
- clipboard behavior; and
- system tray/status notifier behavior.

Some of these helpers also import the generated SonicDE Frameworks Python
modules, such as `KCoreAddons`, `KJobWidgets`, `KGuiAddons`, and
`KStatusNotifierItem`.

These appear to be test applications rather than production desktop
components. They could be replaced with small C++ Qt/KF test executables while
keeping the higher-level Appium test harness in Python.

### `sonic-breeze` and `sonic-silver`

Both cursor projects contain Python build helpers that import
`PySide6.QtSvg.QSvgRenderer`:

```text
src/sonicde/sonic-breeze/cursors/src/generate_cursors
src/sonicde/sonic-breeze/cursors/src/hotspot_test
src/sonicde/sonic-silver/cursors/src/generate_cursors
src/sonicde/sonic-silver/cursors/src/hotspot_test
```

The scripts inspect the SVG element named `hotspot`, transform its bounds, and
write cursor metadata. This is a good candidate for a small C++ utility using
`QSvgRenderer` and `Qt6::Svg`. Qt 6.11 provides `QSvgRenderer` through the
`Qt6::Svg` CMake target and exposes the element bounds/transform operations used
by the scripts.

### Framework examples

Python examples in Core Addons, GUI Addons, Notifications, Status Notification,
and Widgets Addons import PySide6 and their generated framework modules. They
would need to be removed, retained only in external Python-binding packaging, or
ported to equivalent C++ examples.

## Replacement inventory after native test migration

Assuming the PySide-based Appium fixtures are replaced with native QML/C++
tests, the Breeze and Silver cursor tools are the only remaining operational
programs that require functionally equivalent replacements.

### Programs that must be ported

```text
src/sonicde/sonic-breeze/cursors/src/generate_cursors
src/sonicde/sonic-breeze/cursors/src/hotspot_test
src/sonicde/sonic-silver/cursors/src/generate_cursors
src/sonicde/sonic-silver/cursors/src/hotspot_test
```

The two projects currently carry equivalent implementations. A small C++
utility linked to `Qt6::Svg` can replace the Python/PySide implementation. It
must preserve:

- lookup of the SVG element named `hotspot`;
- application of the element transform to its bounds;
- the existing one-hundredth-pixel displacement and floor rounding behavior;
- animated cursor frame handling;
- XCursor configuration generation;
- `xcursorgen` invocation; and
- scalable cursor `metadata.json` output.

The companion `hotspot_test` scripts should be ported with the generator rather
than overlooked as development-only utilities.

### Content that should be removed, not replaced

#### Python-binding trees

The following repositories contain binding headers, Shiboken typesystems,
generated-source declarations, and wheel installation logic under their
`python/` directories:

- `sonic-frameworks-core-addons`
- `sonic-frameworks-gui-addons`
- `sonic-frameworks-notifications`
- `sonic-frameworks-progress-ui`
- `sonic-frameworks-status-notification`
- `sonic-frameworks-unit-conversion`
- `sonic-frameworks-widgets-addons`
- `sonic-frameworks-xml-gui`

These trees define the Python products being discontinued and therefore do not
need native replacements. Their top-level `BUILD_PYTHON_BINDINGS` options,
PySide/Shiboken package discovery, and `add_subdirectory(python)` branches
should be removed at the same time.

#### Framework Python examples

Python examples in Core Addons, GUI Addons, Notifications, Status Notification,
and Widgets Addons demonstrate APIs that will no longer exist. They can be
deleted without replacement unless preserving example coverage is a separate
project requirement. Several corresponding native C++ tests or examples
already exist.

#### ECM binding infrastructure

If the repository-wide consumer search remains empty after removing the eight
framework binding trees, the following Extra CMake Modules content can be
removed rather than replaced:

```text
modules/ECMGeneratePythonBindings.cmake
modules/ECMGeneratePythonBindings.toml.in
docs/module/ECMGeneratePythonBindings.rst
```

Its entry in `modules/CMakeLists.txt` should also be removed.

### Builder and package cleanup

The removal requires configuration changes but no replacement implementation:

1. Remove `sonic-pyside` from the active solution.
2. Remove the `sonic-pyside` package manifest.
3. Remove `sonic-pyside` from the eight framework package manifests.
4. Remove `python3-build`, `python3-setuptools`, and `python3-wheel` from those
   manifests where they were present solely to package binding wheels.
5. Regenerate `state/model.json`, `repo-list`, generated CMake files, and the
   dependency graph.

### CI and packaging cleanup

The following should be retired rather than replaced:

- CI configurations that enable or test `BUILD_PYTHON_BINDINGS`;
- installation and packaging of the eight generated Python modules;
- checks for PySide6 and Shiboken6 development files; and
- Python-wheel validation for these framework modules.

### Textual references that are not dependencies

A Frameworks Feeds test fixture and localization templates contain textual
mentions of PySide6. They do not import, link, execute, or otherwise depend on
PySide. They can remain unless the project also wants to eliminate every
textual reference to the name.

## Required migration

### Remove the Python bindings

The generated Python bindings must be removed to eliminate PySide and Shiboken
from the SonicDE build.

Expected work:

1. Stop building the Python-binding subdirectories in the eight framework
   repositories.
2. Remove their `find_package(PySide6)` and `find_package(Shiboken6)` calls.
3. Remove the corresponding `sonic-pyside` build dependencies from package
   manifests.
4. Remove `sonic-pyside` from the active solution.
5. Remove Python wheel-only build dependencies where no longer needed.
6. Port or retire framework Python examples.
7. Port the `sonic-workspace` PySide-based Appium helper applications to C++.
8. Port the Breeze and Silver cursor helpers to a shared or duplicated C++
   `Qt6::Svg` utility.
9. Remove `ECMGeneratePythonBindings` only if it has no remaining consumers.

Benefits:

- Removes a large and complex source package from the superbuild.
- Removes the Shiboken generator and runtime from the supported stack.
- Avoids Qt/Python/PySide ABI synchronization issues.
- Makes the affected build path entirely native C++/Qt.

Costs and risks:

- Removes the published `KCoreAddons`, `KGuiAddons`, `KNotifications`,
  `KJobWidgets`, `KStatusNotifierItem`, `KUnitConversion`, `KWidgetsAddons`, and
  `KXmlGui` Python modules.
- Breaks downstream Python applications that consume those modules.
- Requires replacement test fixtures to preserve existing Appium coverage.
- Cross-repository changes must land in a coordinated order.

Overall feasibility: **high**, provided removal of the Python API is acceptable.

## Recommended direction

Remove the generated Python binding layer completely. Replace the PySide-based
Appium fixtures with native QML/C++ tests and port the Breeze/Silver cursor
generator and `hotspot_test` utilities to C++ with `Qt6::Svg`. No other
discovered operational component requires a replacement; the remaining
binding infrastructure, examples, packaging, and CI support should be removed.

## Suggested validation before implementation

Before committing to removal:

1. Confirm whether SonicDE promises the generated Frameworks Python modules as
   public API.
2. Search packaging metadata outside this builder for packages or applications
   that require those modules.
3. Regenerate `state/model.json` so it reflects the `sonic-pyside` rename.
4. Generate the dependency graph and verify all direct and transitive edges.
5. Inventory CI jobs that enable `BUILD_PYTHON_BINDINGS` or execute Python
   examples.
6. Inventory Appium tests that depend on generated bindings and define C++
   replacement fixtures.
7. Prototype one cursor helper in C++ with `Qt6::Svg` to validate identical
   hotspot rounding and metadata output.
8. Prototype removal in the least-coupled framework before changing the full
   cross-repository set.
