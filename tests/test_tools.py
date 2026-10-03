"""Running and fetching the external tools, without running any of them."""

from __future__ import annotations

import email.message
import io
import os
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import pytest

from ksp_source_annotator import KspSourceAnnotatorError, Workspace, tools


def test_download_retries_transient_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def urlopen(request: urllib.request.Request, **_: object) -> io.BytesIO:
        calls.append(request.full_url)
        if len(calls) < 3:
            raise urllib.error.URLError("connection reset")
        return io.BytesIO(b"payload")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    dest = tmp_path / "sub" / "file.bin"
    tools.download("https://example.invalid/file.bin", dest)
    assert len(calls) == 3
    assert dest.read_bytes() == b"payload"
    assert list(dest.parent.iterdir()) == [dest]


def test_download_gives_up_on_client_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def urlopen(request: urllib.request.Request, **_: object) -> io.BytesIO:
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", email.message.Message(), io.BytesIO())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    dest = tmp_path / "file.bin"
    with pytest.raises(KspSourceAnnotatorError, match="download failed"):
        tools.download("https://example.invalid/file.bin", dest)
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_fetch_de4dot_source_strips_the_archive_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def download(url: str, dest: Path) -> None:
        assert url == tools.DE4DOT_URL
        with tarfile.open(dest, "w:gz") as tar:
            for name, data in (
                (f"de4dot-{tools.DE4DOT_COMMIT}/de4dot/de4dot.csproj", b"<Project/>"),
                (f"de4dot-{tools.DE4DOT_COMMIT}/README.md", b"readme"),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))

    monkeypatch.setattr(tools, "download", download)
    src = tmp_path / "de4dot-src"
    src.mkdir()
    _ = (src / "stale.txt").write_text("from an earlier fetch")
    tools._fetch_de4dot_source(src)  # pyright: ignore[reportPrivateUsage]
    assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()) == [
        "COMMIT",
        "README.md",
        "de4dot/de4dot.csproj",
    ]
    assert tools._de4dot_source_version(src) == tools.DE4DOT_COMMIT  # pyright: ignore[reportPrivateUsage]
    assert not (tmp_path / "de4dot-src.tar.gz").exists()


def test_missing_program_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-program"
    with pytest.raises(KspSourceAnnotatorError, match="could not run"):
        tools.run([missing])
    with pytest.raises(KspSourceAnnotatorError, match="could not run"):
        tools.run([missing], log_file=tmp_path / "log.txt")
    with pytest.raises(KspSourceAnnotatorError, match="could not run"):
        _ = tools.capture([missing])


def test_ilspycmd_is_installed_at_the_pinned_version(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def run(cmd: Sequence[str | Path], **_: object) -> None:
        commands.append([str(c) for c in cmd])
        local = workspace.tools / "ilspycmd" / f"ilspycmd{tools.EXE}"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.touch()

    monkeypatch.setattr(shutil, "which", lambda _name: None)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    monkeypatch.setattr(tools, "run", run)
    monkeypatch.setattr(tools, "capture", lambda _cmd: "ilspycmd: 11.1.0.9782\n")  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    tool = tools.find_ilspycmd(workspace)
    assert tool.version == "ilspycmd: 11.1.0.9782"
    assert len(commands) == 1 and commands[0][4:6] == ["--version", tools.ILSPYCMD_VERSION]
    # Installed once, then reused.
    _ = tools.find_ilspycmd(workspace)
    assert len(commands) == 1


def test_symdump_is_built_only_when_its_sources_change(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    builds: list[list[str]] = []

    def run(cmd: Sequence[str | Path], **_: object) -> None:
        builds.append([str(c) for c in cmd])
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.touch()

    dll = workspace.tools / "symdump" / "bin" / "Release" / "net8.0" / "symdump.dll"
    monkeypatch.setattr(tools, "require", lambda program: program)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    monkeypatch.setattr(tools, "run", run)
    assert tools.build_symdump(workspace) == dll
    assert tools.build_symdump(workspace) == dll
    assert len(builds) == 1
    # A copied source that differs from the package's is replaced, and that rebuilds.
    program = workspace.tools / "symdump" / "Program.cs"
    _ = program.write_text("edited")
    os.utime(dll, (1000, 1000))
    assert tools.build_symdump(workspace) == dll
    assert len(builds) == 2
    assert program.read_text() != "edited"
