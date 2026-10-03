"""Merge KSP API documentation sources into .NET XML documentation files.

Sources, in priority order (the first source to document a symbol wins):
  1. official  Squad's Doxygen XML package for KSP 1.12.4
  2. anatid    community Assembly-CSharp.xml (2015)
  3. wiki      MediaWiki export of the KSP wiki's API: namespace
  4. game      the game's own en-us UI text, for symbols whose attributes
               carry localization keys (tooltips and labels)

Every entry is keyed by the documentation comment ID Roslyn assigns to the
symbol in the installed assemblies (symbols.json, from symdump), so entries
for symbols that no longer exist are dropped instead of written.

Output is one <Assembly>.xml per assembly, the layout the C# language server
reads when the file sits beside <Assembly>.dll.
"""

from __future__ import annotations

import collections
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from .anatid import anatid_docs
from .doc import Doc, Report
from .doxygen import Doxygen
from .game import game_docs
from .symbols import Symbols
from .wiki import wiki_docs


def merge_docs(
    symbols: Symbols | str | os.PathLike[str],
    out: str | os.PathLike[str],
    *,
    official: str | os.PathLike[str] | None = None,
    anatid: str | os.PathLike[str] | None = None,
    wiki: str | os.PathLike[str] | None = None,
    gamedata: str | os.PathLike[str] | None = None,
) -> Report:
    """Build each given source, merge them in priority order, and write the
    XML files, REPORT.txt, and UNMATCHED.txt into out. Documentation XML
    files already in out for assemblies this run documents nothing in are
    removed.

    symbols is a Symbols or the path of a symbols.json from symdump.
    official is the Doxygen xml.zip, anatid is anatid's Assembly-CSharp.xml,
    wiki is a MediaWiki XML export, and gamedata is the game's GameData
    directory. A source left as None is skipped.
    """
    report = Report()
    syms = symbols if isinstance(symbols, Symbols) else Symbols.load(symbols)
    layers: list[tuple[str, dict[str, Doc]]] = []
    if official is not None:
        dox = Doxygen(syms, report)
        dox.load(official)
        layers.append(("official", dox.docs()))
    if anatid is not None:
        layers.append(("anatid", anatid_docs(anatid, syms, report)))
    if wiki is not None:
        layers.append(("wiki", wiki_docs(wiki, syms, report)))
    if gamedata is not None:
        layers.append(("game", game_docs(gamedata, syms, report)))

    merged: dict[str, Doc] = {}
    for name, docs in layers:
        for sid, d in docs.items():
            if d.empty():
                continue
            # A fragment that is not well-formed would corrupt the whole file.
            try:
                _ = ET.fromstring(f"<member>{d.render()}</member>")
            except ET.ParseError:
                report.stats[f"{name}: entries dropped as malformed"] += 1
                continue
            report.stats[f"{name}: symbols documented"] += 1
            if sid in merged:
                report.stats[f"{name}: already documented by a higher-priority source"] += 1
            else:
                merged[sid] = d
                report.stats[f"{name}: entries written"] += 1

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_asm: dict[str, list[str]] = collections.defaultdict(list)
    for sid in sorted(merged):
        by_asm[syms.by_id[sid]["asm"]].append(sid)
    for asm, ids in sorted(by_asm.items()):
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>\n<doc>\n',
            f"  <assembly>\n    <name>{escape(asm)}</name>\n  </assembly>\n  <members>\n",
        ]
        for sid in ids:
            lines.append(f"    <member name={quoteattr(sid)}>{merged[sid].render()}</member>\n")
        lines.append("  </members>\n</doc>\n")
        document = "".join(lines)
        _ = ET.fromstring(document)
        _ = (out_dir / f"{asm}.xml").write_text(document, encoding="utf-8")
        report.stats[f"output: {asm}.xml entries"] = len(ids)
    for stale in sorted(out_dir.glob("*.xml")):
        if stale.stem not in by_asm and _is_assembly_doc(stale):
            stale.unlink()
            report.stats["output: stale XML files removed"] += 1

    _ = (out_dir / "UNMATCHED.txt").write_text(
        "".join("\t".join(row) + "\n" for row in sorted(report.unmatched)), encoding="utf-8"
    )
    _ = (out_dir / "REPORT.txt").write_text(report.format() + "\n", encoding="utf-8")
    return report


def _is_assembly_doc(path: Path) -> bool:
    """Whether path is a .NET XML documentation file for the assembly its
    name gives, the shape merge_docs writes."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return False
    return root.tag == "doc" and root.findtext("assembly/name") == path.stem
