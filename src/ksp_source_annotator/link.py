"""Step 4: symlink the XML documentation into the KSP install, and undo it."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .errors import KspSourceAnnotatorError
from .install import KspInstall
from .workspace import Workspace

log = logging.getLogger(__name__)


def link_apidocs(install: KspInstall, workspace: Workspace) -> list[Path]:
    """Symlink each built <Assembly>.xml beside <Assembly>.dll in the install.

    Language servers show a documentation file when it sits beside the
    assembly a project references. Existing symlinks are updated. A file with
    no matching assembly is skipped. A regular file with the same name is left
    alone, and after the rest are linked an error is raised that names it.
    This and unlink_apidocs are the only steps that write to the install.
    Returns the links made.
    """
    docs = workspace.version_dir(install.read_version()) / "apidocs"
    files = sorted(docs.glob("*.xml"))
    if not files:
        raise KspSourceAnnotatorError(f"no XML files in {docs} (run the apidocs step first)")

    linked: list[Path] = []
    blocked: list[Path] = []
    for xml in files:
        link = install.managed / xml.name
        if not (install.managed / f"{xml.stem}.dll").is_file():
            log.info("skipped %s: no %s.dll in %s", xml.name, xml.stem, install.managed)
            continue
        if link.exists() and not link.is_symlink():
            blocked.append(link)
            continue
        try:
            link.unlink(missing_ok=True)
            link.symlink_to(xml)
        except OSError as e:
            hint = (
                " (on Windows, creating symlinks needs Developer Mode or an administrator)" if os.name == "nt" else ""
            )
            raise KspSourceAnnotatorError(f"could not link {link} to {xml}: {e.strerror or e}{hint}") from e
        linked.append(link)
        log.info("linked %s -> %s", link, xml)
    if blocked:
        raise KspSourceAnnotatorError(
            "not replacing files that are not symlinks: " + ", ".join(str(p) for p in blocked)
        )
    return linked


def unlink_apidocs(install: KspInstall, workspace: Workspace) -> list[Path]:
    """Remove the symlinks link_apidocs made in the install.

    Only symlinks named <Assembly>.xml beside the assemblies, and pointing into
    one of the workspace's KSP-<version>/ directories, are removed, whether or
    not their target still exists. Returns the links removed.
    """
    version_dirs = workspace.version_dirs()
    removed: list[Path] = []
    for link in sorted(install.managed.glob("*.xml")):
        if not link.is_symlink():
            continue
        target = link.parent / link.readlink()
        if not any(target.is_relative_to(d) for d in version_dirs):
            continue
        try:
            link.unlink()
        except OSError as e:
            raise KspSourceAnnotatorError(f"could not remove {link}: {e.strerror or e}") from e
        removed.append(link)
        log.info("unlinked %s", link)
    return removed
