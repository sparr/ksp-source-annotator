"""Step 1: decompile the game's managed assemblies into C# projects."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .errors import KspSourceAnnotatorError
from .install import KspInstall
from .tools import Tool, capture, find_de4dot, find_ilspycmd, require, run
from .workspace import Workspace

log = logging.getLogger(__name__)

OBFUSCATED = ("Assembly-CSharp",)
"""Only Assembly-CSharp is obfuscated. The others are read as shipped."""

EXPORT = ("Assembly-CSharp", "KSPAssets")
"""The assemblies exported as C# projects."""


def decompile(install: KspInstall, workspace: Workspace, *, force: bool = False) -> Path:
    """Decompile the install into the workspace's KSP-<version>/ directory.

    de4dot strips the Crypto Obfuscator control flow from Assembly-CSharp,
    then ilspycmd exports each assembly as a C# project. Each tool is skipped
    when its output is newer than both its input and this package's files,
    so a second run only redoes what changed; force runs both regardless. A project that is exported again
    loses the comments written by annotate_source, which has to be run again.
    The install is only read. Returns the output directory.
    """
    version = install.read_version()
    out = workspace.version_dir(version)
    deobfuscated = out / "deobfuscated"
    deobfuscated.mkdir(parents=True, exist_ok=True)
    de4dot: Tool | None = None
    ilspycmd: Tool | None = None

    for asm in OBFUSCATED:
        source = install.managed / f"{asm}.dll"
        cleaned = deobfuscated / f"{asm}.dll"
        if not force and _up_to_date(cleaned, source):
            log.info("== de4dot %s: up to date", asm)
            continue
        _ = require("dotnet")
        de4dot = de4dot or find_de4dot(workspace)
        log.info("== de4dot %s", asm)
        cleaned.unlink(missing_ok=True)
        # --dont-rename keeps identifiers matching what mods bind against.
        output = capture([*de4dot.command, "--dont-rename", "-f", source, "-o", cleaned])
        for line in output.splitlines():
            if line.startswith(("Detected", "ERROR", "WARNING")):
                log.info("%s", line)
        if not cleaned.is_file() or cleaned.stat().st_size == 0:
            raise KspSourceAnnotatorError(f"de4dot produced no output for {asm}")

    for asm in EXPORT:
        project_dir = out / asm
        # The project file is patched last, so it is the newest file of a
        # finished export.
        project = project_dir / f"{asm}.csproj"
        source = deobfuscated / f"{asm}.dll"
        if not source.is_file():
            source = install.managed / f"{asm}.dll"
        if not force and _up_to_date(project, source):
            log.info("== ilspycmd %s: up to date", asm)
            continue
        _ = require("dotnet")
        ilspycmd = ilspycmd or find_ilspycmd(workspace)
        log.info("== ilspycmd %s", asm)
        # Start empty, so no file from an earlier export is left behind.
        if project_dir.exists():
            shutil.rmtree(project_dir)
        project_dir.mkdir()
        # C# 7.3 is what Unity 2019.4 compiles. The deobfuscated directory is
        # listed first so references to Assembly-CSharp resolve to the cleaned copy.
        run(
            [
                *ilspycmd.command,
                "--disable-updatecheck",
                "-p",
                "--nested-directories",
                "-lv",
                "CSharp7_3",
                "-r",
                deobfuscated,
                "-r",
                install.managed,
                "-o",
                project_dir,
                source,
            ],
            log_file=out / f"{asm}.ilspy.log",
            what=f"ilspycmd for {asm}",
        )
        # ilspycmd writes net40, whose mscorlib lacks types that the game's
        # System.Core forwards to it, which breaks every extension method.
        _ = project.write_bytes(
            project.read_bytes().replace(
                b"<TargetFramework>net40</TargetFramework>", b"<TargetFramework>net48</TargetFramework>"
            )
        )
        log.info("   %d files", sum(1 for _ in project_dir.rglob("*.cs")))

    if de4dot or ilspycmd:
        _write_version(out / "VERSION.txt", install, de4dot, ilspycmd)
    log.info("done: %s", out)
    return out


def _up_to_date(output: Path, source: Path) -> bool:
    """True when output exists and was written no earlier than source or
    than any file of this package, whose code may have changed the output."""
    try:
        return output.stat().st_mtime >= max(source.stat().st_mtime, _package_mtime())
    except FileNotFoundError:
        return False


def _package_mtime() -> float:
    """When a file of this package was last modified, installed or not."""
    root = Path(__file__).parent
    return max(
        (p.stat().st_mtime for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts), default=0.0
    )


def _write_version(path: Path, install: KspInstall, de4dot: Tool | None, ilspycmd: Tool | None) -> None:
    """Record the game version and the versions of the tools that made the
    output. A tool that did not run this time keeps its line from before."""
    version = install.read_version()
    previous = path.read_text().splitlines() if path.is_file() else []

    def earlier(prefix: str) -> str:
        return next((line for line in previous if line.startswith(prefix)), f"{prefix} unknown")

    _ = path.write_text(
        f"KSP {version.version} build {version.build}\n"
        f"source: {install.managed}\n"
        + (f"de4dot: {de4dot.version} (--dont-rename)\n" if de4dot else earlier("de4dot:") + "\n")
        + (f"{ilspycmd.version}\n" if ilspycmd else earlier("ilspycmd:") + "\n")
    )
