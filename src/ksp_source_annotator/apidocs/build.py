"""Step 2: build XML documentation files for the game's assemblies."""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path

from ..errors import KspSourceAnnotatorError
from ..install import KspInstall
from ..tools import build_symdump, download, run
from ..workspace import Workspace
from .doc import Report
from .merge import merge_docs

log = logging.getLogger(__name__)

ASSEMBLIES = ("Assembly-CSharp", "Assembly-CSharp-firstpass", "KSPAssets")
"""The assemblies whose symbols are listed and documented."""

OFFICIAL_URL = "https://web.archive.org/web/20230306021650id_/https://www.kerbalspaceprogram.com/ksp/api/xml.zip"
"""Squad's Doxygen XML package for KSP 1.12.4, from the Wayback Machine."""

ANATID_COMMIT = "338e0fe797ccced9814c3c1d2712dc2362d3afe5"
"""Known good commit"""
ANATID_URL = (
    f"https://raw.githubusercontent.com/Anatid/XML-Documentation-for-the-KSP-API/{ANATID_COMMIT}/Assembly-CSharp.xml"
)
"""anatid's community documentation file."""


def fetch_sources(workspace: Workspace) -> tuple[Path, Path]:
    """Download the official and anatid sources into the workspace's cache
    unless they are already there. Returns their paths, in that order."""
    official = workspace.downloads / "official-doxygen-xml.zip"
    if not official.is_file() or official.stat().st_size == 0:
        log.info("== downloading the official Doxygen XML package")
        part = official.with_name(official.name + ".unchecked")
        download(OFFICIAL_URL, part)
        if not zipfile.is_zipfile(part):
            raise KspSourceAnnotatorError(f"download is not a zip archive: {part}")
        _ = part.replace(official)
    anatid = workspace.downloads / "anatid" / "Assembly-CSharp.xml"
    if not anatid.is_file():
        log.info("== fetching anatid documentation")
        download(ANATID_URL, anatid)
    return official, anatid


def build_apidocs(install: KspInstall, workspace: Workspace, *, wiki: str | os.PathLike[str] | None = None) -> Report:
    """Build the XML documentation into KSP-<version>/apidocs/ in the workspace.

    wiki is a MediaWiki XML export to use as a source, by default the newest
    one in the workspace; with none, that source is skipped. The official and
    anatid sources are downloaded on first use. The install is only read.
    Returns the merge report, which is also written to REPORT.txt and
    UNMATCHED.txt beside the XML files.
    """
    version = install.read_version()
    out = workspace.version_dir(version) / "apidocs"
    if wiki is None:
        wiki = workspace.newest_wiki_export()
        if wiki is None:
            log.info("note: no wiki export found, building without it")
    elif not Path(wiki).is_file():
        raise KspSourceAnnotatorError(f"wiki export not found: {wiki}")

    official, anatid = fetch_sources(workspace)
    symdump = build_symdump(workspace)
    out.mkdir(parents=True, exist_ok=True)

    log.info("== listing symbols in KSP %s", version)
    symbols = out / "symbols.json"
    try:
        run(["dotnet", symdump, "dump", install.managed, symbols, *ASSEMBLIES], what="symdump dump")
        log.info("== merging documentation")
        report = merge_docs(symbols, out, official=official, anatid=anatid, wiki=wiki, gamedata=install.gamedata)
    finally:
        symbols.unlink(missing_ok=True)
    log.info("%s", report.format())

    log.info("== verifying with Roslyn")
    run(["dotnet", symdump, "verify", install.managed, out, *ASSEMBLIES], what="symdump verify")
    log.info("done: %s", out)
    return report
