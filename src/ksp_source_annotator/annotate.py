"""Step 3: write the merged documentation into the decompiled source."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .errors import KspSourceAnnotatorError
from .install import KspInstall
from .tools import build_symdump, run
from .workspace import Workspace

log = logging.getLogger(__name__)


def annotate_source(
    install: KspInstall, workspace: Workspace, version_dir: str | os.PathLike[str] | None = None
) -> list[str]:
    """Write the XML documentation into the decompiled source as /// comments.

    The source is edited in place; comments written by an earlier run are
    replaced. version_dir is the KSP-<version> directory to annotate, by
    default the one for the install's version. Run after decompile and
    build_apidocs. The install is only read. Returns the names of the
    assemblies annotated.
    """
    out = Path(version_dir).resolve() if version_dir is not None else workspace.version_dir(install.read_version())
    if not out.is_dir():
        raise KspSourceAnnotatorError(f"{out} does not exist (run the decompile step first)")
    pairs = [(xml, out / xml.stem) for xml in sorted((out / "apidocs").glob("*.xml"))]
    pairs = [(xml, src) for xml, src in pairs if src.is_dir()]
    if not pairs:
        raise KspSourceAnnotatorError(
            f"no apidocs/<Assembly>.xml matches a source directory in {out} (run the apidocs step first)"
        )
    symdump = build_symdump(workspace)
    for xml, src in pairs:
        log.info("== annotating %s", xml.stem)
        run(["dotnet", symdump, "annotate", install.managed, xml, src], what="symdump annotate")
    return [xml.stem for xml, _ in pairs]
