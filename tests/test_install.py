"""Locating an install, reading its version, and the workspace layout."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import NoReturn

import pytest

from ksp_source_annotator import KspInstall, KspSourceAnnotatorError, Workspace, find_installs
from ksp_source_annotator.install import FINDER_MODULE
from ksp_source_annotator.workspace import user_cache_dir


def test_locate_reads_version(install: KspInstall) -> None:
    version = install.read_version()
    assert (version.version, version.build) == ("1.12.5", "3190")
    assert version.dir_name == "KSP-1.12.5.3190"
    assert install.managed == install.root / "KSP_Data" / "Managed"


def test_locate_from_environment(install: KspInstall, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KSP_ROOT", str(install.root))
    assert KspInstall.locate() == install
    # An explicit root wins over the environment.
    with pytest.raises(KspSourceAnnotatorError, match="not a directory"):
        _ = KspInstall.locate(install.root / "missing")


def test_locate_x64_data_dir(tmp_path: Path) -> None:
    managed = tmp_path / "KSP_x64_Data" / "Managed"
    managed.mkdir(parents=True)
    (managed / "Assembly-CSharp.dll").touch()
    assert KspInstall.locate(tmp_path).managed == managed


def test_locate_errors(tmp_path: Path) -> None:
    with pytest.raises(KspSourceAnnotatorError, match="not a directory"):
        _ = KspInstall.locate(tmp_path / "missing")
    with pytest.raises(KspSourceAnnotatorError, match=r"no Assembly-CSharp\.dll"):
        _ = KspInstall.locate(tmp_path)


def test_unreadable_version(install: KspInstall) -> None:
    (install.root / "buildID.txt").unlink()
    with pytest.raises(KspSourceAnnotatorError, match="could not read the game version"):
        _ = install.read_version()


def test_newest_wiki_export(workspace: Workspace) -> None:
    assert workspace.newest_wiki_export() is None
    old = workspace.root / "Kerbal+Space+Program+Wiki-20250101000000.xml"
    new = workspace.root / "Kerbal+Space+Program+Wiki-20260101000000.xml"
    old.touch()
    new.touch()
    # The timestamp in the name decides, not when the file was last touched.
    os.utime(new, (1000, 1000))
    os.utime(old, (2000, 2000))
    assert workspace.newest_wiki_export() == new


def test_clean_keeps_inputs(workspace: Workspace) -> None:
    export = workspace.root / "Kerbal+Space+Program+Wiki-20260101000000.xml"
    export.touch()
    for name in ("KSP-1.12.5.3190", "KSP-1.8.1.2694"):
        (workspace.root / name / "sub").mkdir(parents=True)
    # Directories that only start with KSP- are not output of this package.
    kept = [export.name, "KSP-mods", "KSP-1.12.5.3190-backup"]
    for name in kept[1:]:
        (workspace.root / name).mkdir()
    (workspace.tools / "de4dot").mkdir(parents=True)
    removed = workspace.clean()
    assert sorted(p.name for p in removed) == ["KSP-1.12.5.3190", "KSP-1.8.1.2694"]
    assert sorted(p.name for p in workspace.root.iterdir()) == sorted(kept)
    # The cache is kept unless asked for.
    assert workspace.tools.is_dir()


def test_clean_cache(workspace: Workspace) -> None:
    (workspace.tools / "de4dot").mkdir(parents=True)
    (workspace.downloads / "anatid").mkdir(parents=True)
    assert workspace.clean(cache=True) == [workspace.tools, workspace.downloads, workspace.cache_dir]
    assert not workspace.cache_dir.exists()
    # A cache directory that holds anything else keeps it.
    (workspace.tools / "de4dot").mkdir(parents=True)
    other = workspace.cache_dir / "other.txt"
    other.parent.mkdir(parents=True, exist_ok=True)
    _ = other.write_text("not ours")
    assert workspace.clean(cache=True) == [workspace.tools]
    assert sorted(workspace.cache_dir.iterdir()) == [other]
    # Cleaning a cache that was never made is not an error.
    assert Workspace.at(workspace.root, workspace.root.parent / "none").clean(cache=True) == []


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("linux", {"XDG_CACHE_HOME": "/xdg"}, "/xdg/app"),
        ("linux", {}, "{home}/.cache/app"),
        ("darwin", {"XDG_CACHE_HOME": "/xdg"}, "{home}/Library/Caches/app"),
        ("win32", {"LOCALAPPDATA": "/local"}, "/local/app/Cache"),
        ("win32", {}, "{home}/AppData/Local/app/Cache"),
    ],
)
def test_user_cache_dir(
    platform: str, env: dict[str, str], expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    # Path.home() reads USERPROFILE on Windows and HOME elsewhere, so set it directly.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for name in ("XDG_CACHE_HOME", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert user_cache_dir("app") == Path(expected.format(home=tmp_path))


def test_default_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    workspace = Workspace.at(tmp_path)
    assert workspace.cache_dir == tmp_path / "xdg" / "ksp-source-annotator"
    assert workspace.tools == workspace.cache_dir / "tools"
    assert workspace.downloads == workspace.cache_dir / "downloads"


def test_locate_relative_path(install: KspInstall, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(install.root.parent)
    located = KspInstall.locate(install.root.name)
    assert located.root.is_absolute()
    assert located == install


def test_locate_macos_layout(tmp_path: Path) -> None:
    managed = tmp_path / "KSP.app" / "Contents" / "Resources" / "Data" / "Managed"
    managed.mkdir(parents=True)
    (managed / "Assembly-CSharp.dll").touch()
    assert KspInstall.locate(tmp_path).managed == managed


def make_install(root: Path) -> Path:
    """Create the one file that makes a directory a KSP install."""
    managed = root / "KSP_Data" / "Managed"
    managed.mkdir(parents=True)
    (managed / "Assembly-CSharp.dll").touch()
    return root


def fake_finder(monkeypatch: pytest.MonkeyPatch, *games: tuple[str, str | None, str, Path]) -> None:
    """Stand in for the vendored finder with these (launcher, appid, name, path) games."""
    cli = ModuleType(FINDER_MODULE)
    cli.get_steam_path = lambda: Path("/steam")  # pyright: ignore[reportAttributeAccessIssue]

    def index(*, steam_root: Path | None = None) -> list[SimpleNamespace]:
        assert steam_root == Path("/steam")
        return [
            SimpleNamespace(launcher=launcher, appid=appid, name=name, path=path)
            for launcher, appid, name, path in games
        ]

    cli.build_installed_game_index = index  # pyright: ignore[reportAttributeAccessIssue]
    monkeypatch.setitem(sys.modules, FINDER_MODULE, cli)
    monkeypatch.delenv("KSP_ROOT", raising=False)


def test_found_in_launcher_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ksp = make_install(tmp_path / "steam" / "Kerbal Space Program")
    fake_finder(
        monkeypatch,
        ("steam", "220200", "Kerbal Space Program", ksp),
        # The same install listed by a second launcher is not a second install.
        ("lutris", "7", "kerbal space program", ksp),
        ("steam", "954850", "Kerbal Space Program 2", make_install(tmp_path / "ksp2")),
        # A library entry whose files are gone.
        ("heroic", None, "Kerbal Space Program", tmp_path / "uninstalled"),
    )
    assert [i.root for i in find_installs()] == [ksp]
    assert KspInstall.locate().root == ksp


def test_environment_wins_over_launcher_library(
    install: KspInstall, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_finder(monkeypatch, ("steam", "220200", "Kerbal Space Program", make_install(tmp_path / "steam")))
    monkeypatch.setenv("KSP_ROOT", str(install.root))
    assert KspInstall.locate() == install


def test_launcher_library_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_finder(monkeypatch)
    with pytest.raises(KspSourceAnnotatorError, match="no KSP install found"):
        _ = KspInstall.locate()
    steam, gog = make_install(tmp_path / "steam"), make_install(tmp_path / "gog")
    fake_finder(
        monkeypatch,
        ("steam", "220200", "Kerbal Space Program", steam),
        ("heroic", "1429864849", "Kerbal Space Program", gog),
    )
    with pytest.raises(KspSourceAnnotatorError, match="more than one KSP install found") as e:
        _ = KspInstall.locate()
    assert str(steam) in str(e.value) and str(gog) in str(e.value)


def test_finder_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_finder(monkeypatch)

    def broken(**_: object) -> NoReturn:
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(sys.modules[FINDER_MODULE], "build_installed_game_index", broken)
    with pytest.raises(KspSourceAnnotatorError, match=r"searching the game launcher libraries failed \(file is not"):
        _ = KspInstall.locate()


def test_vendored_finder_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A home directory with no launchers in it, so nothing is found.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / name))
    assert find_installs() == []
