"""All the steps in order."""

from __future__ import annotations

import os
from pathlib import Path

from .annotate import annotate_source
from .apidocs import build_apidocs
from .decompile import decompile
from .install import KspInstall
from .link import link_apidocs
from .workspace import Workspace


def run_all(
    install: KspInstall,
    workspace: Workspace,
    *,
    wiki: str | os.PathLike[str] | None = None,
    force: bool = False,
    link: bool = False,
) -> Path:
    """Decompile, build the documentation, and annotate the source.

    force runs de4dot and ilspycmd even when their output is newer than
    their input and this package's files.
    link also symlinks the documentation into the install, which is the only
    part that writes there. Returns the KSP-<version>/ output directory.
    """
    out = decompile(install, workspace, force=force)
    _ = build_apidocs(install, workspace, wiki=wiki)
    _ = annotate_source(install, workspace, out)
    if link:
        _ = link_apidocs(install, workspace)
    return out
