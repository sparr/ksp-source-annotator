"""Source 4: the game's own en-us UI text."""

from __future__ import annotations

import os
import re
from pathlib import Path
from xml.sax.saxutils import escape

from .doc import Doc, Report
from .symbols import Symbols

STOCK_DIRS = {"Squad", "SquadExpansion"}
"""GameData directories that ship with the game: the base game and the expansions."""

TOOLTIP_ARGS = {"tooltip", "hovertext", "tiptext"}
"""Attribute argument names (lowercased) whose text is a sentence describing the member."""

LABEL_ARGS = {"guiname", "title", "description"}
"""Attribute argument names (lowercased) whose text is the short name shown for the member."""


def load_localization(gamedata: str | os.PathLike[str]) -> dict[str, str]:
    """en-us strings from the stock dictionaries, keyed by lowercased tag.
    Mods' dictionaries are not read, since they may reword stock strings."""
    strings: dict[str, str] = {}
    base = Path(gamedata)
    for root, _, files in base.walk():
        rel = root.relative_to(base).parts
        if not rel or rel[0] not in STOCK_DIRS or root.name != "Localization":
            continue
        for f in files:
            if not f.endswith(".cfg"):
                continue
            text = (root / f).read_text(encoding="utf-8-sig", errors="replace")
            block = re.search(r"en-us\s*\{(.*?)\n\s*\}", text, re.S)
            if not block:
                continue
            for entry in re.finditer(r"^\s*(#\S+)\s*=\s*(.*)$", str(block.group(1)), re.M):
                key, value = str(entry.group(1)), str(entry.group(2))
                strings[key.lower()] = re.sub(r"\s+", " ", value.replace("\\n", " ")).strip()
    return strings


def game_docs(gamedata: str | os.PathLike[str], syms: Symbols, report: Report) -> dict[str, Doc]:
    """Entries built from the in-game tooltip and label text attached to symbols."""
    strings = load_localization(gamedata)
    out: dict[str, Doc] = {}
    for sym in syms.all:
        tooltip: str | None = None
        label: str | None = None
        for _attr, arg, key in sym["loc"] or []:
            report.stats["game: localization keys on symbols"] += 1
            text = strings.get(key.lower())
            if not text:
                report.stats["game: keys with no en-us string"] += 1
                report.unmatched.append(("game", "key has no en-us string", f"{sym['id']} {arg}={key}"))
            elif arg.lower() in TOOLTIP_ARGS:
                tooltip = tooltip or text
            elif arg.lower() in LABEL_ARGS:
                label = label or text
        # A label that only repeats the identifier says nothing new.
        ident = re.sub(r"[\W_]", "", sym["name"]).lower()
        if label and re.sub(r"[\W_]", "", label).lower() == ident:
            label = None
        d = Doc("game")
        if tooltip:
            report.stats["game: symbols with a tooltip"] += 1
            d.summary = escape(tooltip)
            if label:
                d.remarks.append(f"In-game label: {escape(label)}")
        elif label:
            report.stats["game: symbols with only a label"] += 1
            d.summary = f"In-game label: {escape(label)}"
        else:
            continue
        d.remarks.append("Source: game UI text (en-us localization).")
        out[sym["id"]] = d
    return out
