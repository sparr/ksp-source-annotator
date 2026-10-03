"""The Roslyn helper's annotate command, on a small source file. Needs dotnet,
and network access the first time, to restore the Roslyn packages."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ksp_source_annotator import Workspace
from ksp_source_annotator.tools import build_symdump

DATA = Path(__file__).parent / "data" / "annotate"

pytestmark = [pytest.mark.dotnet, pytest.mark.skipif(shutil.which("dotnet") is None, reason="needs dotnet")]


def runtime_assemblies() -> Path:
    """The directory of the newest installed .NET runtime, whose assemblies
    stand in for the game's as references."""
    listing = subprocess.run(["dotnet", "--list-runtimes"], capture_output=True, text=True, check=True).stdout
    found = [(m[1], m[2]) for m in re.finditer(r"^Microsoft\.NETCore\.App (\S+) \[(.*)\]$", listing, re.M)]
    if not found:
        pytest.skip("no .NET runtime found")
    version, base = found[-1]
    return Path(base) / version


def test_annotate_writes_and_replaces_comments(workspace: Workspace, tmp_path: Path) -> None:
    src = tmp_path / "Foo"
    src.mkdir()
    _ = shutil.copy(DATA / "Foo.cs", src / "Foo.cs")
    symdump = build_symdump(workspace)
    command = ["dotnet", str(symdump), "annotate", str(runtime_assemblies()), str(DATA / "Foo.xml"), str(src)]

    first = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    assert first.strip() == "Foo: 12 of 13 documentation entries written into 1 files"
    expected = (DATA / "Foo.expected.cs").read_text()
    assert (src / "Foo.cs").read_text() == expected

    # A second run replaces its own comments with the same text.
    second = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    assert second.strip() == "Foo: 12 of 13 documentation entries written into 0 files"
    assert (src / "Foo.cs").read_text() == expected
