"""The external programs the steps run: dotnet, de4dot, ilspycmd, and symdump."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import BinaryIO, cast

from .errors import KspSourceAnnotatorError
from .workspace import Workspace

log = logging.getLogger(__name__)

# de4dot has no releases and its repo is archived, so unless one is already
# installed, build it from source.
# Known good: commit b7d5728fc0c82fb0ad758e3a4c0fbb70368a4853, the tip of master.
DE4DOT_COMMIT = "b7d5728fc0c82fb0ad758e3a4c0fbb70368a4853"
DE4DOT_URL = f"https://github.com/de4dot/de4dot/archive/{DE4DOT_COMMIT}.tar.gz"

ILSPYCMD_VERSION = "11.1.0.9782"
"""The ilspycmd installed when none is on PATH. It runs on .NET 10."""

USER_AGENT = "ksp-source-annotator (+https://pypi.org/project/ksp-source-annotator/)"

EXE = ".exe" if os.name == "nt" else ""
"""The file name suffix of a native executable on this platform."""


def require(program: str) -> str:
    """The path of a program on PATH, or an error naming it."""
    path = shutil.which(program)
    if path is None:
        raise KspSourceAnnotatorError(f"{program} not found")
    return path


def _niced(cmd: Sequence[str | Path]) -> list[str]:
    """The command as strings, at the lowest CPU priority where nice exists.
    Raises if the program cannot be found, which nice would only report as an
    exit status."""
    if shutil.which(str(cmd[0])) is None:
        raise KspSourceAnnotatorError(f"could not run {cmd[0]}: not found")
    nice = shutil.which("nice")
    return ([nice, "-n", "19"] if nice else []) + [str(c) for c in cmd]


def _start_failed(cmd: Sequence[str | Path], e: OSError) -> KspSourceAnnotatorError:
    """The error for a command that could not be started at all."""
    return KspSourceAnnotatorError(f"could not run {cmd[0]}: {e.strerror or e}")


def run(cmd: Sequence[str | Path], *, log_file: Path | None = None, what: str = "") -> None:
    """Run a command at low priority and raise if it fails.

    Output goes to log_file when one is given, otherwise to this process's
    stdout and stderr. what names the command in the error message.
    """
    what = what or str(cmd[0])
    try:
        if log_file is None:
            code = subprocess.run(_niced(cmd), check=False).returncode
            if code != 0:
                raise KspSourceAnnotatorError(f"{what} failed with exit status {code}")
            return
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("wb") as out:
            code = subprocess.run(_niced(cmd), stdout=out, stderr=subprocess.STDOUT, check=False).returncode
    except OSError as e:
        raise _start_failed(cmd, e) from e
    if code != 0:
        raise KspSourceAnnotatorError(f"{what} failed, see {log_file}")


def capture(cmd: Sequence[str | Path]) -> str:
    """Run a command at low priority and return its stdout, whatever its exit status."""
    try:
        return subprocess.run(_niced(cmd), stdout=subprocess.PIPE, text=True, errors="replace", check=False).stdout
    except OSError as e:
        raise _start_failed(cmd, e) from e


def download(url: str, dest: Path, *, retries: int = 3) -> None:
    """Fetch url to dest, by way of a .part file so dest is never partial."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            response = cast("BinaryIO", urllib.request.urlopen(request, timeout=120))
            with response, part.open("wb") as f:
                shutil.copyfileobj(response, f)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            # A 4xx answer will not change; anything else may be transient.
            permanent = False
            if isinstance(e, urllib.error.HTTPError):
                permanent = 400 <= e.code < 500
                e.close()  # the error holds the open response body
            if permanent or attempt == retries:
                part.unlink(missing_ok=True)
                raise KspSourceAnnotatorError(f"download failed: {url} ({e})") from e
            time.sleep(2.0**attempt)
    _ = part.replace(dest)


# ------------------------------------------------------------------ de4dot


@dataclass(frozen=True)
class Tool:
    """A command prefix and a description of the version it runs."""

    command: tuple[str, ...]
    version: str


def find_de4dot(workspace: Workspace) -> Tool:
    """de4dot from PATH, or built from source into the cache's tools/."""
    on_path = shutil.which("de4dot")
    if on_path:
        return Tool((on_path,), on_path)
    src = workspace.tools / "de4dot-src"
    dll = workspace.tools / "de4dot" / "de4dot.dll"
    if not dll.is_file():
        log.info("== building de4dot")
        project = src / "de4dot" / "de4dot.csproj"
        if not project.is_file():
            _fetch_de4dot_source(src)
        # Upstream targets netcoreapp3.1 with LangVersion=latest. Retarget to
        # net8.0, let it run on any newer runtime, pin the language (C# 14 makes
        # 'field' a keyword), and allow the BinaryFormatter uses that net8.0
        # turns into errors.
        run(
            [
                "dotnet",
                "build",
                project,
                "-c",
                "Release",
                "-nologo",
                "-v",
                "q",
                "-f",
                "net8.0",
                "-p:TargetFrameworks=net8.0",
                "-p:SolutionName=de4dot.netcore",
                "-p:RollForward=Major",
                "-p:LangVersion=8.0",
                "-p:NoWarn=SYSLIB0011",
                "-p:EnableUnsafeBinaryFormatterSerialization=true",
                "-o",
                dll.parent,
            ],
            log_file=workspace.tools / "de4dot-build.log",
            what="de4dot build",
        )
    return Tool(("dotnet", str(dll)), _de4dot_source_version(src))


def _fetch_de4dot_source(src: Path) -> None:
    """Download and unpack the pinned de4dot commit into src."""
    archive = src.with_name("de4dot-src.tar.gz")
    download(DE4DOT_URL, archive)
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        # Every path in the archive is under one directory named for the commit.
        for member in tar.getmembers():
            _, _, rest = member.name.partition("/")
            if not rest:
                continue
            member.name = rest
            tar.extract(member, src, filter="data")
    _ = (src / "COMMIT").write_text(DE4DOT_COMMIT + "\n")
    archive.unlink()


def _de4dot_source_version(src: Path) -> str:
    """The commit the source tree in src was taken from."""
    marker = src / "COMMIT"
    if marker.is_file():
        return marker.read_text().strip()
    # A tree cloned by hand, or by the shell scripts this package replaced.
    if (src / ".git").exists() and shutil.which("git"):
        return capture(["git", "-C", src, "rev-parse", "HEAD"]).strip() or "unknown"
    return "unknown"


# ---------------------------------------------------------------- ilspycmd


def find_ilspycmd(workspace: Workspace) -> Tool:
    """ilspycmd from PATH, or installed as a dotnet tool into the cache's tools/."""
    # Known good: ilspycmd 11.0.0.9375 and 11.1.0.9782.
    path = shutil.which("ilspycmd")
    if path is None:
        tool_dir = workspace.tools / "ilspycmd"
        local = tool_dir / f"ilspycmd{EXE}"
        if not local.is_file():
            log.info("== installing ilspycmd %s", ILSPYCMD_VERSION)
            run(
                ["dotnet", "tool", "install", "ilspycmd", "--version", ILSPYCMD_VERSION, "--tool-path", tool_dir],
                log_file=workspace.tools / "ilspycmd-install.log",
                what="ilspycmd install",
            )
        path = str(local)
    version = capture([path, "--version"]).splitlines()
    return Tool((path,), version[0] if version else "ilspycmd: unknown version")


# ----------------------------------------------------------------- symdump


def build_symdump(workspace: Workspace) -> Path:
    """Build the Roslyn helper that ships with this package; returns its dll.

    The C# sources are copied out of the package into the cache's tools/
    so the build never writes into the installed package. The build is
    skipped when the dll is newer than every source.
    """
    _ = require("dotnet")
    build_dir = workspace.tools / "symdump"
    dll = build_dir / "bin" / "Release" / "net8.0" / "symdump.dll"
    build_dir.mkdir(parents=True, exist_ok=True)
    sources: list[Path] = []
    for source in resources.files(__package__).joinpath("symdump").iterdir():
        if not source.is_file():
            continue
        data = source.read_bytes()
        target = build_dir / source.name
        sources.append(target)
        # Leave unchanged files alone so their times say when they last changed.
        if not target.is_file() or target.read_bytes() != data:
            _ = target.write_bytes(data)
    if dll.is_file() and dll.stat().st_mtime >= max(s.stat().st_mtime for s in sources):
        return dll
    log.info("== building symdump")
    run(
        ["dotnet", "build", build_dir / "symdump.csproj", "-c", "Release", "-nologo", "-v", "q"],
        log_file=workspace.tools / "symdump-build.log",
        what="symdump build",
    )
    return dll
