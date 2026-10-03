"""Source 1: Squad's official Doxygen XML package."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape, quoteattr

from .doc import Doc, Report
from .symbols import Symbol, Symbols, norm, split_top

OPERATORS = {
    "operator+": "op_Addition",
    "operator-": "op_Subtraction",
    "operator*": "op_Multiply",
    "operator/": "op_Division",
    "operator%": "op_Modulus",
    "operator==": "op_Equality",
    "operator!=": "op_Inequality",
    "operator<": "op_LessThan",
    "operator>": "op_GreaterThan",
    "operator<=": "op_LessThanOrEqual",
    "operator>=": "op_GreaterThanOrEqual",
    "operator!": "op_LogicalNot",
    "operator~": "op_OnesComplement",
    "operator++": "op_Increment",
    "operator--": "op_Decrement",
    "operator&": "op_BitwiseAnd",
    "operator|": "op_BitwiseOr",
    "operator^": "op_ExclusiveOr",
    "operator<<": "op_LeftShift",
    "operator>>": "op_RightShift",
    "operator true": "op_True",
    "operator false": "op_False",
}
"""Doxygen's binary and fixed-arity operator names mapped to the method names
the compiler emits."""

UNARY_OPERATORS = {"operator+": "op_UnaryPlus", "operator-": "op_UnaryNegation"}
"""Operators whose one-parameter form is a different method from their two-parameter form."""

CONVERSIONS = {"implicit": "op_Implicit", "explicit": "op_Explicit"}
"""Conversion operators, which Doxygen names "operator <Type>" and gives the
type "implicit" or "explicit"."""

DOXYGEN_KINDS = {"function": "Method", "variable": "Field", "property": "Property", "event": "Event"}
"""Doxygen member kinds mapped to Roslyn symbol kinds."""


def read_doxygen_xml(data: bytes) -> ET.Element:
    """Parse one file from the Doxygen package, repairing its known encoding faults."""
    # Some files declare UTF-8 but contain Windows-1252 bytes, and about 160
    # have a bare "&" in source paths such as "Career Modules/R&D".
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    text = re.sub(r"^<\?xml[^>]*\?>", "", text)
    text = re.sub(r"&(?!(?:[a-zA-Z]+|#[0-9]+|#x[0-9a-fA-F]+);)", "&amp;", text)
    return ET.fromstring(text)


def el_text(e: ET.Element | None) -> str:
    """All text inside an element, stripped; empty for a missing element."""
    return "".join(e.itertext()).strip() if e is not None else ""


class Doxygen:
    """Reads the official Doxygen XML package and converts its descriptions.

    load() matches every compound and member to a symbol; docs() then renders
    the matched descriptions, once all cross-reference targets are known."""

    def __init__(self, syms: Symbols, report: Report) -> None:
        self.syms: Symbols = syms
        self.report: Report = report
        # doxygen id -> doc comment ID
        self.refmap: dict[str, str] = {}
        # (symbol, brief description, detailed description)
        self.pending: list[tuple[Symbol, ET.Element | None, ET.Element | None]] = []

    def load(self, zip_path: str | os.PathLike[str]) -> None:
        """Read every XML file in the zip and match its contents to symbols."""
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                if not name.endswith(".xml") or name.endswith("index.xml"):
                    continue
                try:
                    root = read_doxygen_xml(z.read(name))
                except ET.ParseError:
                    self.report.stats["official: unparseable files"] += 1
                    continue
                for cd in root.findall("compounddef"):
                    self.compound(cd)

    def compound(self, cd: ET.Element) -> None:
        """Match one compound (a type, namespace, or file) and the members it lists."""
        kind = cd.get("kind")
        if kind in ("dir", "page", "example", "group"):
            return
        # Namespace and file compounds are only read for the enums they hold.
        container = "" if kind == "file" else el_text(cd.find("compoundname")).replace("::", ".")
        is_type = kind not in ("file", "namespace")
        if is_type:
            sym = self.syms.types.get(norm(container))
            self.note(cd, sym, "types", container, "no type with this name")
        for m in cd.iter("memberdef"):
            if m.get("kind") == "enum":
                self.enum(container, m)
            elif is_type:
                sym, reason = self.member(container, m)
                label = f"{container}.{el_text(m.find('name'))}{el_text(m.find('argsstring'))}"
                if norm(container) not in self.syms.types:
                    reason = "containing type not found"
                self.note(m, sym, "members", label, reason)

    def enum(self, container: str, m: ET.Element) -> None:
        """Match an enum and each of its values."""
        full = (container + "." if container else "") + el_text(m.find("name"))
        sym = self.syms.types.get(norm(full))
        self.note(m, sym, "enums", full, "no enum with this name")
        if sym is None:
            return
        for v in m.findall("enumvalue"):
            name = el_text(v.find("name"))
            self.note(
                v,
                self.syms.find_member(sym["full"], name, "Field")[0],
                "enum values",
                f"{full}.{name}",
                "enum exists, no value with this name",
            )

    def member(self, container: str, m: ET.Element) -> tuple[Symbol | None, str]:
        """Find the symbol for a memberdef, or None with the reason it was not found."""
        kind = m.get("kind", "")
        raw = el_text(m.find("name"))
        name = re.sub(r"<.*", "", raw).strip()
        generic = re.search(r"<(.*)>", raw)
        tparams = len(split_top(generic.group(1))) if generic else 0
        simple = re.sub(r"<.*", "", container.split(".")[-1])
        ptypes: list[str] | None = None
        prefs: list[str] | None = None
        if kind == "function":
            if name == simple:
                name = ".cctor" if m.get("static") == "yes" else ".ctor"
            elif name.startswith("~"):
                name = "Finalize"
            elif name.startswith("operator "):
                name = CONVERSIONS.get(el_text(m.find("type")), name)
            elif name in UNARY_OPERATORS and len(m.findall("param")) == 1:
                name = UNARY_OPERATORS[name]
            name = OPERATORS.get(name, name)
        indexer = re.match(r"this\s*(\[.*\])?$", raw.strip())
        if indexer:
            # Parameters are in the name or in argsstring, as "[int index]".
            name, kind = "this[]", "property"
            inner = (indexer.group(1) or el_text(m.find("argsstring"))).strip().strip("[]")
            declared = [a.strip().rsplit(None, 1)[0] for a in split_top(inner) if a.strip()]
        else:
            declared = [el_text(p.find("type")) for p in m.findall("param")]
        if kind == "function" or name == "this[]":
            ptypes, prefs = [], []
            for t in declared:
                t = re.sub(r"\[[^\]]*\]\s*(?=\S)", "", t) if t.startswith("[") else t
                leading = re.match(r"^((?:(?:ref|out|in|params|this)\s+)*)", t)
                mods = str(leading.group(1)).split() if leading else []
                prefs.append("Ref" if "ref" in mods else "Out" if "out" in mods else "In" if "in" in mods else "None")
                ptypes.append(t.split(None, len(mods))[-1] if mods else t)
        return self.syms.find_member(
            container,
            name,
            DOXYGEN_KINDS.get(kind),
            len(ptypes) if ptypes is not None else None,
            ptypes,
            tparams if kind == "function" else None,
            prefs,
        )

    def note(self, el: ET.Element, sym: Symbol | None, what: str, label: str, reason: str) -> None:
        """Record a matched element for cross-references, and queue or report its description."""
        has_doc = bool(el_text(el.find("briefdescription")) or el_text(el.find("detaileddescription")))
        if sym is not None:
            self.refmap[el.get("id", "")] = sym["id"]
        if not has_doc:
            return
        self.report.stats[f"official: documented {what}"] += 1
        if sym is None:
            self.report.stats[f"official: {what} with no unique 1.12.5 symbol"] += 1
            self.report.unmatched.append(("official", reason, label))
        else:
            self.pending.append((sym, el.find("briefdescription"), el.find("detaileddescription")))

    def docs(self) -> dict[str, Doc]:
        """Render the queued descriptions into entries keyed by documentation ID."""
        out: dict[str, Doc] = {}
        for sym, brief, detailed in self.pending:
            d = Doc("official")
            paras = self.blocks(brief, d) + self.blocks(detailed, d)
            paras = [p for p in paras if p]
            d.summary = paras[0] if len(paras) == 1 else "".join(f"<para>{p}</para>" for p in paras)
            pnames = sym["pnames"]
            if pnames is not None:
                for n in [n for n in d.params if n not in pnames]:
                    del d.params[n]
            if d.empty():
                self.report.stats["official: entries with no text"] += 1
            elif sym["id"] in out:
                self.report.stats["official: entries for a symbol already documented by this source"] += 1
            else:
                out[sym["id"]] = d
        return out

    def blocks(self, desc: ET.Element | None, d: Doc) -> list[str]:
        """Render each top-level paragraph of a description."""
        return [self.inline(p, d) for p in desc.findall("para")] if desc is not None else []

    def inline(self, e: ET.Element, d: Doc) -> str:
        """Render a description element, moving structured parts into d."""
        out = escape(e.text or "")
        for c in e:
            out += self.child(c, d) + escape(c.tail or "")
        return re.sub(r"\s+", " ", out).strip()

    def child(self, c: ET.Element, d: Doc) -> str:
        """Render one child element of a description as doc-comment XML."""
        tag = c.tag
        if tag == "parameterlist":
            kind = c.get("kind")
            for item in c.findall("parameteritem"):
                name = el_text(item.find("parameternamelist"))
                text = self.inline_all(item.find("parameterdescription"), d)
                if not (name and text):
                    continue
                if kind == "param":
                    d.params[name] = text
                elif kind == "templateparam":
                    d.typeparams[name] = text
                elif kind == "exception":
                    d.remarks.append(f"Throws {escape(name)}: {text}")
            return ""
        if tag == "simplesect":
            text = self.inline_all(c, d)
            kind = c.get("kind")
            if not text or kind == "author":
                return ""
            if kind == "return":
                d.returns = text
            elif kind == "see":
                d.remarks.append("See also: " + text)
            else:
                d.remarks.append(text)
            return ""
        if tag == "ref":
            target = self.refmap.get(c.get("refid", ""))
            return f"<see cref={quoteattr(target)}/>" if target else escape(el_text(c))
        if tag == "ulink":
            return f"<see href={quoteattr(c.get('url', ''))}>{self.inline(c, d)}</see>"
        if tag == "computeroutput":
            return f"<c>{self.inline(c, d)}</c>"
        if tag in ("emphasis", "bold"):
            t = "i" if tag == "emphasis" else "b"
            return f"<{t}>{self.inline(c, d)}</{t}>"
        if tag in ("itemizedlist", "orderedlist"):
            items = "".join(
                f"<item><description>{self.inline_all(li, d)}</description></item>" for li in c.findall("listitem")
            )
            return f'<list type="{"bullet" if tag == "itemizedlist" else "number"}">{items}</list>'
        if tag in ("ndash", "mdash"):
            return "-"
        return self.inline(c, d)

    def inline_all(self, e: ET.Element | None, d: Doc) -> str:
        """Render an element that may hold several paragraphs as one run of text."""
        if e is None:
            return ""
        paras = e.findall("para")
        if not paras:
            return self.inline(e, d)
        return " ".join(p for p in (self.inline(p, d) for p in paras) if p)
