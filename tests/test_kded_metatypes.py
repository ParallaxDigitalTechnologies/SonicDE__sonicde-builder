#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Regression coverage for kded model metatypes across Qt versions."""
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest


KDED = (
    Path(__file__).parent.parent
    / "src" / "sonicde" / "sonic-desktop-interface" / "kcms" / "kded"
)


def test_qobject_models_are_not_declared_opaque():
    source = (KDED / "kcmkded.h").read_text(encoding="utf-8")
    for model, header in (
        ("ModulesModel", "modulesmodel.h"),
        ("FilterProxyModel", "filterproxymodel.h"),
    ):
        assert f"class {model};" in source
        assert f'Q_MOC_INCLUDE("{header}")' in source
        assert f"Q_DECLARE_OPAQUE_POINTER({model} *)" not in source


def test_combined_moc_compiles_with_complete_qobject_metatypes(tmp_path):
    """Exercise the real headers and moc in CMake's combined include order.

    Only the framework base is stubbed: this test needs Qt Core, not a full
    desktop installation. Run it with each supported Qt toolchain to cover
    changes to moc and metatype completeness checks.
    """
    compiler = shutil.which("c++")
    pkg_config = shutil.which("pkg-config")
    if not compiler or not pkg_config:
        pytest.skip("C++ compiler and pkg-config required")
    probe = subprocess.run(
        [pkg_config, "--exists", "Qt6Core"], check=False,
    )
    if probe.returncode:
        pytest.skip("Qt6Core development files required")

    def qt_config(option):
        return subprocess.check_output(
            [pkg_config, option, "Qt6Core"], text=True,
        ).strip()

    moc = Path(qt_config("--variable=libexecdir")) / "moc"
    if not moc.is_file():
        pytest.skip("Qt6 moc required")
    flags = shlex.split(qt_config("--cflags"))
    (tmp_path / "KQuickConfigModule").write_text(
        "#pragma once\n"
        "#include <QObject>\n"
        "class KQuickConfigModule : public QObject {\n"
        "public:\n"
        "    virtual void load() {}\n"
        "    virtual void save() {}\n"
        "    virtual void defaults() {}\n"
        "};\n",
        encoding="utf-8",
    )
    headers = ("filterproxymodel", "kcmkded", "modulesmodel")
    for header in headers:
        subprocess.run(
            [str(moc), *flags, f"-I{tmp_path}", f"-I{KDED}",
             str(KDED / f"{header}.h"),
             "-o", str(tmp_path / f"moc_{header}.cpp")],
            check=True, capture_output=True, text=True,
        )
    generated = (tmp_path / "moc_kcmkded.cpp").read_text(encoding="utf-8")
    assert '#include "modulesmodel.h"' in generated
    assert '#include "filterproxymodel.h"' in generated

    combined = tmp_path / "mocs_compilation.cpp"
    combined.write_text(
        "".join(f'#include "moc_{header}.cpp"\n' for header in headers),
        encoding="utf-8",
    )
    result = subprocess.run(
        [compiler, "-std=c++20", "-fPIC", "-fsyntax-only", *flags,
         f"-I{tmp_path}", f"-I{KDED}", str(combined)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
