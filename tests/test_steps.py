"""The parts of the steps that run without .NET tooling, and the command line."""

from __future__ import annotations

import importlib
import os
import time
from pathlib import Path
from typing import NoReturn

import pytest

from ksp_source_annotator import (
    KspInstall,
    KspSourceAnnotatorError,
    Workspace,
    annotate_source,
    decompile,
    link_apidocs,
    unlink_apidocs,
)
from ksp_source_annotator.cli import main

# The package exports the function under the module's name, so fetch the module.
decompile_module = importlib.import_module("ksp_source_annotator.decompile")
install_module = importlib.import_module("ksp_source_annotator.install")


def make_docs(install: KspInstall, workspace: Workspace, *names: str) -> Path:
    """Create empty apidocs XML files for the install's version."""
    docs = workspace.version_dir(install.read_version()) / "apidocs"
    docs.mkdir(parents=True)
    for name in names:
        (docs / f"{name}.xml").touch()
    return docs


def test_link_creates_and_updates(install: KspInstall, workspace: Workspace) -> None:
    docs = make_docs(install, workspace, "Assembly-CSharp", "Assembly-CSharp-firstpass", "KSPAssets")
    stale = install.managed / "Assembly-CSharp.xml"
    stale.symlink_to(workspace.root / "elsewhere.xml")

    linked = link_apidocs(install, workspace)

    # KSPAssets.dll is not in the install, so its file is skipped.
    assert sorted(p.name for p in linked) == ["Assembly-CSharp-firstpass.xml", "Assembly-CSharp.xml"]
    assert stale.readlink() == docs / "Assembly-CSharp.xml"
    assert not (install.managed / "KSPAssets.xml").exists()


def test_link_leaves_regular_files(install: KspInstall, workspace: Workspace) -> None:
    _ = make_docs(install, workspace, "Assembly-CSharp", "Assembly-CSharp-firstpass")
    mine = install.managed / "Assembly-CSharp.xml"
    _ = mine.write_text("mine")

    with pytest.raises(KspSourceAnnotatorError, match="not symlinks"):
        _ = link_apidocs(install, workspace)

    assert mine.read_text() == "mine"
    assert (install.managed / "Assembly-CSharp-firstpass.xml").is_symlink()


def test_link_needs_docs(install: KspInstall, workspace: Workspace) -> None:
    with pytest.raises(KspSourceAnnotatorError, match="run the apidocs step first"):
        _ = link_apidocs(install, workspace)


def test_decompile_skips_up_to_date_output(
    install: KspInstall, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = workspace.version_dir(install.read_version())
    outputs = [
        out / "deobfuscated" / "Assembly-CSharp.dll",
        out / "Assembly-CSharp" / "Assembly-CSharp.csproj",
        out / "KSPAssets" / "KSPAssets.csproj",
    ]
    (install.managed / "KSPAssets.dll").touch()
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        _ = path.write_text("output")
    for dll in install.managed.glob("*.dll"):
        os.utime(dll, (1000, 1000))

    def tool_needed(_: Workspace) -> NoReturn:
        raise AssertionError("a tool ran")

    monkeypatch.setattr(decompile_module, "find_de4dot", tool_needed)
    monkeypatch.setattr(decompile_module, "find_ilspycmd", tool_needed)
    monkeypatch.setattr(decompile_module, "require", lambda _program: "dotnet")  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    assert decompile(install, workspace) == out
    assert all(p.read_text() == "output" for p in outputs)

    # A newer game assembly makes its de4dot output stale, and only that one.
    os.utime(install.managed / "Assembly-CSharp.dll")
    with pytest.raises(AssertionError, match="a tool ran"):
        _ = decompile(install, workspace)
    os.utime(install.managed / "Assembly-CSharp.dll", (1000, 1000))
    with pytest.raises(AssertionError, match="a tool ran"):
        _ = decompile(install, workspace, force=True)
    # So does a newer copy of this package.
    assert decompile(install, workspace) == out
    monkeypatch.setattr(decompile_module, "_package_mtime", lambda: time.time() + 60)
    with pytest.raises(AssertionError, match="a tool ran"):
        _ = decompile(install, workspace)


def test_annotate_needs_docs(install: KspInstall, workspace: Workspace) -> None:
    with pytest.raises(KspSourceAnnotatorError, match="run the decompile step first"):
        _ = annotate_source(install, workspace)
    # Documentation with no source directory of the same name is not enough.
    _ = make_docs(install, workspace, "Assembly-CSharp")
    with pytest.raises(KspSourceAnnotatorError, match="run the apidocs step first"):
        _ = annotate_source(install, workspace)


def test_cli_reports_errors(install: KspInstall, workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    status = main(
        [
            "link",
            "--ksp-dir",
            str(install.root),
            "--work-dir",
            str(workspace.root),
            "--cache-dir",
            str(workspace.cache_dir),
        ]
    )
    assert status == 1
    assert capsys.readouterr().err.startswith("error: no XML files in ")


def test_cli_link_and_clean(install: KspInstall, workspace: Workspace) -> None:
    _ = make_docs(install, workspace, "Assembly-CSharp")
    common = [
        "--ksp-dir",
        str(install.root),
        "--work-dir",
        str(workspace.root),
        "--cache-dir",
        str(workspace.cache_dir),
    ]
    assert main(["link", *common]) == 0
    assert (install.managed / "Assembly-CSharp.xml").is_symlink()
    workspace.tools.mkdir(parents=True)
    assert main(["clean", *common]) == 0
    assert list(workspace.root.iterdir()) == []
    assert not (install.managed / "Assembly-CSharp.xml").exists()
    assert not (install.managed / "Assembly-CSharp.xml").is_symlink()
    assert workspace.tools.is_dir()
    assert main(["clean", "--cache", *common]) == 0
    assert not workspace.cache_dir.exists()


def test_unlink_removes_only_links_into_the_workspace(install: KspInstall, workspace: Workspace) -> None:
    docs = make_docs(install, workspace, "Assembly-CSharp", "Assembly-CSharp-firstpass")
    _ = link_apidocs(install, workspace)
    elsewhere = install.managed / "UnityEngine.xml"
    elsewhere.symlink_to(workspace.root.parent / "other" / "UnityEngine.xml")
    regular = install.managed / "Other.xml"
    _ = regular.write_text("mine")
    # A link whose target is already gone is still removed.
    (docs / "Assembly-CSharp-firstpass.xml").unlink()

    removed = unlink_apidocs(install, workspace)

    assert sorted(p.name for p in removed) == ["Assembly-CSharp-firstpass.xml", "Assembly-CSharp.xml"]
    assert sorted(p.name for p in install.managed.glob("*.xml")) == ["Other.xml", "UnityEngine.xml"]
    assert elsewhere.is_symlink()


def test_cli_clean_without_an_install(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KSP_ROOT", raising=False)
    monkeypatch.setattr(install_module, "find_installs", list)
    (workspace.root / "KSP-1.12.5.3190").mkdir()
    assert main(["clean", "--work-dir", str(workspace.root), "--cache-dir", str(workspace.cache_dir)]) == 0
    assert list(workspace.root.iterdir()) == []


def test_cli_clean_with_a_named_install_that_is_missing(workspace: Workspace, tmp_path: Path) -> None:
    (workspace.root / "KSP-1.12.5.3190").mkdir()
    args = ["--ksp-dir", str(tmp_path / "missing"), "--work-dir", str(workspace.root)]
    assert main(["clean", *args, "--cache-dir", str(workspace.cache_dir)]) == 1
    # Nothing is removed when the named install cannot be cleaned.
    assert (workspace.root / "KSP-1.12.5.3190").is_dir()
