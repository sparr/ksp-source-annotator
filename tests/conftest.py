"""Fixtures shared by the tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ksp_source_annotator import KspInstall, Workspace


@pytest.fixture
def install(tmp_path: Path) -> KspInstall:
    """A directory laid out like a KSP 1.12.5 build 3190 install, with empty assemblies."""
    root = tmp_path / "Kerbal Space Program"
    managed = root / "KSP_Data" / "Managed"
    managed.mkdir(parents=True)
    for asm in ("Assembly-CSharp", "Assembly-CSharp-firstpass"):
        (managed / f"{asm}.dll").touch()
    _ = (root / "readme.txt").write_text("Kerbal Space Program\nVersion 1.12.5\n")
    _ = (root / "buildID.txt").write_text("build id = 03190\n2023.01.01 at 00:00:00 CET\n")
    return KspInstall.locate(root)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """An empty workspace, with a cache directory of its own that does not exist yet."""
    root = tmp_path / "work"
    root.mkdir()
    return Workspace.at(root, tmp_path / "cache")
