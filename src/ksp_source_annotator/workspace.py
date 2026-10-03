"""The directory that holds the output, and the cache that holds the
downloaded sources and the tools."""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .install import KspVersion

APP_NAME = "ksp-source-annotator"
"""The name of this package's directory in the user's cache directory."""

WIKI_EXPORT_GLOB = "Kerbal+Space+Program+Wiki-*.xml"
"""The file name MediaWiki's Special:Export gives a download from the KSP wiki.
The part the glob matches is the export's timestamp, YYYYMMDDhhmmss."""

VERSION_DIR_RE = re.compile(r"KSP-[0-9]+(?:\.[0-9]+)+")
"""The names KspVersion.dir_name gives output directories, such as KSP-1.12.5.3190."""


def user_cache_dir(app: str = APP_NAME) -> Path:
    """The platform's per-user cache directory for an application:
    %LOCALAPPDATA%\\<app>\\Cache on Windows, ~/Library/Caches/<app> on macOS,
    and $XDG_CACHE_HOME/<app> (by default ~/.cache/<app>) elsewhere."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / app / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / app
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / app


@dataclass(frozen=True)
class Workspace:
    """A working directory and a cache directory.

    The working directory holds one KSP-<version>/ output directory per game
    version, and is where a wiki export is looked for. The cache holds what
    any number of working directories can share: tools/ for the helper
    programs that get built or installed, and downloads/ for the downloaded
    documentation sources.
    """

    root: Path
    cache_dir: Path

    @classmethod
    def at(
        cls, root: str | os.PathLike[str] | None = None, cache_dir: str | os.PathLike[str] | None = None
    ) -> Workspace:
        """The workspace at root, by default the current directory, using
        cache_dir, by default user_cache_dir()."""
        return cls(
            Path(root if root is not None else Path.cwd()).resolve(),
            Path(cache_dir if cache_dir is not None else user_cache_dir()).resolve(),
        )

    @property
    def tools(self) -> Path:
        """Where de4dot, ilspycmd, and symdump are built or installed."""
        return self.cache_dir / "tools"

    @property
    def downloads(self) -> Path:
        """Where downloaded documentation sources are kept."""
        return self.cache_dir / "downloads"

    def version_dir(self, version: KspVersion) -> Path:
        """The output directory for a game version."""
        return self.root / version.dir_name

    def version_dirs(self) -> list[Path]:
        """The output directories in the workspace, for any game version."""
        return sorted(p for p in self.root.glob("KSP-*") if p.is_dir() and VERSION_DIR_RE.fullmatch(p.name))

    def newest_wiki_export(self) -> Path | None:
        """The wiki export in the workspace with the latest timestamp in its name, if any."""
        exports = sorted(self.root.glob(WIKI_EXPORT_GLOB), key=lambda p: p.name)
        return exports[-1] if exports else None

    def clean(self, *, cache: bool = False) -> list[Path]:
        """Remove the output directories, and with cache also the tools and
        downloads in the cache. Wiki exports are inputs and are kept. Returns
        what was removed.

        Only the cache's own subdirectories are removed, then the cache
        directory itself if that leaves it empty, so a cache directory that
        holds anything else is not lost."""
        targets = self.version_dirs()
        if cache:
            targets += [p for p in (self.tools, self.downloads) if p.exists()]
        for path in targets:
            shutil.rmtree(path)
        if cache and self.cache_dir.is_dir() and not any(self.cache_dir.iterdir()):
            self.cache_dir.rmdir()
            targets.append(self.cache_dir)
        return targets
