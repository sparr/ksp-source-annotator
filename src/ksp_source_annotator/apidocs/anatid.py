"""Source 2: anatid's community Assembly-CSharp.xml."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from typing import cast
from xml.sax.saxutils import escape

from .doc import Doc, Report
from .symbols import Symbol, Symbols, split_top


def anatid_docs(path: str | os.PathLike[str], syms: Symbols, report: Report) -> dict[str, Doc]:
    """Entries from anatid's XML file whose IDs still name, or can be remapped to, a symbol."""
    out: dict[str, Doc] = {}
    for m in ET.parse(path).getroot().iter("member"):
        report.stats["anatid: entries"] += 1
        old = m.get("name", "")
        sym, reason = syms.by_id.get(old), ""
        if sym is None:
            sym, reason = anatid_remap(old, syms)
        if sym is None:
            report.stats["anatid: entries with no unique 1.12.5 symbol"] += 1
            report.unmatched.append(("anatid", reason, old))
            continue
        if sym["id"] != old:
            report.stats["anatid: entries remapped to a moved or changed symbol"] += 1
        d = Doc("anatid")
        # A method whose signature changed since 2015 can have lost parameters.
        pnames = sym["pnames"]
        children = [c for c in m if pnames is None or c.tag != "param" or c.get("name") in pnames]
        # ElementTree has decoded the entities in m.text; tostring re-escapes the children.
        raw = escape(m.text or "") + "".join(ET.tostring(c, encoding="unicode") for c in children)
        raw = re.sub(r"\s*\n\s*", " ", raw).strip()
        d.raw = raw + "<remarks>Source: anatid community API documentation (2015).</remarks>"
        if sym["id"] in out:
            report.stats["anatid: entries for a symbol already documented by this source"] += 1
        else:
            out[sym["id"]] = d
    return out


def anatid_remap(old: str, syms: Symbols) -> tuple[Symbol | None, str]:
    """Find the current symbol for an ID whose namespace or signature changed,
    or None with a short reason for Report.unmatched."""
    prefix, rest = old[:1], old[2:]
    m = re.match(r"([^(]*)(?:\((.*)\))?$", rest)
    if m is None:
        return None, "malformed documentation ID"
    qual = str(m.group(1))
    args = cast("str | None", m.group(2))
    if prefix == "T":
        t = syms.find_type(qual)
        return t, "" if t else "no type with this name"
    container, _, name = qual.rpartition(".")
    t = syms.find_type(container)
    if t is None:
        return None, "containing type not found"
    name = {"#ctor": ".ctor", "#cctor": ".cctor"}.get(name, name)
    arity: int | None = None
    ptypes: list[str] | None = None
    tparams: int | None = None
    if prefix == "M":
        # A generic method's ID carries its arity as a suffix: Name``1.
        generic = re.search(r"``(\d+)$", name)
        tparams = int(generic.group(1)) if generic else 0
        name = re.sub(r"``\d+$", "", name)
        ptypes = split_top(args, opens="{(", closes="})") if args else []
        arity = len(ptypes)
    kind = {"M": "Method", "F": "Field", "P": "Property", "E": "Event"}.get(prefix)
    return syms.find_member(t["full"], name, kind, arity, ptypes, tparams)
