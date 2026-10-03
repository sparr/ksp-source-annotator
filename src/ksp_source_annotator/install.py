"""Locating a KSP install and reading its version."""

from __future__ import annotations

import importlib
import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, override

from .errors import KspSourceAnnotatorError

ENV_VAR = "KSP_ROOT"
"""Environment variable naming the install. KSPBuildTools reads the same one."""

STEAM_APPID = "220200"
"""Steam's ID for Kerbal Space Program. KSP 2 is a different app."""

GAME_NAME = "kerbal space program"
"""The game's name in launcher metadata, lowercased. Matched whole, so that
"Kerbal Space Program 2" is not taken for it."""

log = logging.getLogger(__name__)

FINDER_MODULE = "ksp_source_annotator._vendor.game_install_finder.cli"
"""The vendored game-install-finder module that searches launcher libraries."""

MANAGED_DIRS = ("KSP_Data/Managed", "KSP_x64_Data/Managed", "KSP.app/Contents/Resources/Data/Managed")
"""Where the managed assemblies live, relative to the install root: on Linux,
on Windows, and on macOS."""


@dataclass(frozen=True)
class KspVersion:
    """A game version, such as 1.12.5 build 3190."""

    version: str
    build: str

    @override
    def __str__(self) -> str:
        return f"{self.version}.{self.build}"

    @property
    def dir_name(self) -> str:
        """Name of the output directory for this version."""
        return f"KSP-{self}"


@dataclass(frozen=True)
class KspInstall:
    """A KSP install on disk."""

    root: Path
    """The directory holding KSP_Data/ and GameData/."""
    managed: Path
    """The directory holding Assembly-CSharp.dll."""

    @classmethod
    def locate(cls, root: str | os.PathLike[str] | None = None) -> KspInstall:
        """The install at root. When root is None: the one at $KSP_ROOT, else
        the one that find_installs finds in a game launcher's library."""
        if root is None:
            root = os.environ.get(ENV_VAR)
        if not root:
            return cls._find()
        # Absolute, so that VERSION.txt and the link step record a usable path.
        # Not resolved, so a library reached through a symlink keeps its name.
        path = Path(root).absolute()
        if not path.is_dir():
            raise KspSourceAnnotatorError(f"KSP install is not a directory: {path}")
        managed = _managed_dir(path)
        if managed is None:
            raise KspSourceAnnotatorError(f"no Assembly-CSharp.dll under {path}")
        return cls(path, managed)

    @classmethod
    def _find(cls) -> KspInstall:
        """The one install in the launcher libraries, or an error saying what to do."""
        try:
            found = find_installs()
        except Exception as e:  # anything from the vendored finder, whose failures are not typed
            raise KspSourceAnnotatorError(
                f"no KSP install given, and searching the game launcher libraries failed ({e}): "
                "pass --ksp-dir or set KSP_ROOT"
            ) from e
        if not found:
            raise KspSourceAnnotatorError(
                "no KSP install found in a game launcher's library: pass --ksp-dir or set KSP_ROOT"
            )
        if len(found) > 1:
            raise KspSourceAnnotatorError(
                "more than one KSP install found, pass one with --ksp-dir: " + ", ".join(str(i.root) for i in found)
            )
        log.info("found KSP at %s", found[0].root)
        return found[0]

    @property
    def gamedata(self) -> Path:
        """The install's GameData directory."""
        return self.root / "GameData"

    def read_version(self) -> KspVersion:
        """The game version, from readme.txt and buildID.txt."""
        # readme.txt carries "Version 1.12.5", buildID.txt carries "build id = 03190".
        version = _first_match(self.root / "readme.txt", r"^Version ([0-9][0-9.]*)")
        build = _first_match(self.root / "buildID.txt", r"^build id = 0*([0-9]+)")
        if not (version and build):
            raise KspSourceAnnotatorError("could not read the game version from readme.txt and buildID.txt")
        return KspVersion(version, build)


class _Game(Protocol):
    """The fields read from game_install_finder's InstalledGame."""

    @property
    def launcher(self) -> str: ...
    @property
    def appid(self) -> str | None: ...
    @property
    def name(self) -> str | None: ...
    @property
    def path(self) -> Path | None: ...


class _Finder(Protocol):
    """The functions called in game_install_finder.cli."""

    def get_steam_path(self) -> Path | None: ...
    def build_installed_game_index(self, *, steam_root: Path | None = None) -> Sequence[_Game]: ...


def find_installs() -> list[KspInstall]:
    """Every KSP install in the libraries of the game launchers on this
    machine (Steam, Heroic, and Lutris), without duplicates.

    Uses the vendored game-install-finder package. Only launcher metadata on
    disk is read.
    """
    # The package's Python API is the module behind its command line. It is
    # imported here, not at the top, because it is only needed when no install
    # is named.
    finder = cast("_Finder", cast("object", importlib.import_module(FINDER_MODULE)))
    games = finder.build_installed_game_index(steam_root=finder.get_steam_path())
    found: dict[Path, KspInstall] = {}
    for game in games:
        by_id = game.launcher == "steam" and game.appid == STEAM_APPID
        by_name = (game.name or "").strip().lower() == GAME_NAME
        if game.path is None or not (by_id or by_name):
            continue
        managed = _managed_dir(game.path)
        if managed is not None:
            _ = found.setdefault(game.path.resolve(), KspInstall(game.path, managed))
    return list(found.values())


def _managed_dir(root: Path) -> Path | None:
    """The directory under root that holds Assembly-CSharp.dll, if there is one."""
    for sub in MANAGED_DIRS:
        managed = root / sub
        if (managed / "Assembly-CSharp.dll").is_file():
            return managed
    return None


def _first_match(path: Path, pattern: str) -> str | None:
    """Group 1 of the first line of the file that matches, or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else None
