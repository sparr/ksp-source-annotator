"""Source 3: a MediaWiki export of the KSP wiki's API: pages."""

from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from xml.sax.saxutils import escape

from .doc import Doc, Report
from .symbols import Symbols, norm, split_top

WIKI_NS = {"m": "http://www.mediawiki.org/xml/export-0.11/"}
"""XML namespace of MediaWiki export files."""

WIKI_KINDS = {
    "Field": "Field",
    "FieldTemplate": "Field",
    "Property": "Property",
    "Method": "Method",
    "StaticMethod": "Method",
    "PageEnumValue": "Field",
}
"""Wiki template names mapped to Roslyn symbol kinds."""

WIKI_PLACEHOLDER = re.compile(r"^(summary|description) goes here\.?$", re.I)
"""Text left in pages generated from a template and never filled in."""

INLINE_TAGS = "b|big|code|em|i|math|nowiki|s|small|span|strong|sub|tt|u|var"
"""HTML and wiki tags that mark up a run of text within a line."""

BLOCK_TAGS = "blockquote|br|center|dd|div|dl|dt|hr|li|ol|p|pre|table|tbody|td|th|thead|tr|ul"
"""HTML tags that separate the text before them from the text after."""

MATH = re.compile(r"(<math[^>]*>)(.*?)(</math>)", re.S)
"""A LaTeX formula, whose braces are not template markup."""


def wiki_templates(text: str) -> Iterator[tuple[str, dict[str, str]]]:
    """Yield (name, {param: value}) for every template, innermost first.

    As in MediaWiki, the first letter of the name is case-insensitive, so it
    is given uppercased, and unnamed parameters are keyed "1", "2", and so on.
    """
    stack: list[int] = []
    i = 0
    while i < len(text) - 1:
        two = text[i : i + 2]
        if two == "{{":
            stack.append(i)
            i += 2
        elif two == "}}" and stack:
            body = text[stack.pop() + 2 : i]
            parts: list[str] = []
            depth, cur, j = 0, "", 0
            while j < len(body):
                t = body[j : j + 2]
                if t in ("{{", "[["):
                    depth += 1
                    cur += t
                    j += 2
                    continue
                if t in ("}}", "]]"):
                    depth -= 1
                    cur += t
                    j += 2
                    continue
                if body[j] == "|" and depth == 0:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += body[j]
                j += 1
            parts.append(cur)
            name = parts[0].strip()
            params: dict[str, str] = {}
            position = 0
            for p in parts[1:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k.strip()] = v.strip()
                else:
                    position += 1
                    params[str(position)] = p.strip()
            yield name[:1].upper() + name[1:], params
            i += 2
        else:
            i += 1


def wiki_plain(s: str) -> str:
    """Strip wiki markup (links, templates, bold, HTML tags) down to plain text.

    Only known tags are removed, so text in angle brackets such as List<Part>
    is kept. Formulas are left as their LaTeX source.
    """
    s = re.sub(r"\{\{\s*[Tt]ype\s*\|([^}]*)\}\}", r"\1", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", lambda m: re.sub(r"^API:", "", str(m.group(1))), s)
    s = re.sub(r"\[(https?://\S+)\s+([^\]]+)\]", r"\2 (\1)", s)
    s = re.sub(r"'{2,}", "", s)
    s = re.sub(r"<sup>(.*?)</sup>", r"^\1", s)
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(rf"</?(?:{INLINE_TAGS})(?:\s[^>]*)?/?>", "", s, flags=re.I)
    s = re.sub(rf"</?(?:{BLOCK_TAGS})(?:\s[^>]*)?/?>", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def wiki_text(s: str) -> str:
    """Wikitext to escaped doc-comment XML, keeping code samples as <code>."""
    out: list[str] = []
    pieces: list[str] = re.split(r"<(?:syntaxhighlight|source)[^>]*>(.*?)</(?:syntaxhighlight|source)>", s, flags=re.S)
    for i, piece in enumerate(pieces):
        if i % 2:
            out.append(f"<code>{escape(piece.strip())}</code>")
        else:
            out.append(escape(wiki_plain(piece)))
    return " ".join(p for p in out if p).strip()


def wiki_args(args: str) -> list[tuple[str, str, str]]:
    """(type, name, description) for each parameter in a template's args:
    {{arg|type|name|array=[]|desc=...}} pieces, or plain "Type name" text.
    The name and description are empty when the page does not give them."""
    out: list[tuple[str, str, str]] = []
    for piece in split_top(args, opens="<([{", closes=">)]}"):
        piece = piece.strip()
        if not piece:
            continue
        templates = list(wiki_templates(piece))
        # The outermost template is yielded last.
        if templates and templates[-1][0] == "Arg" and piece.startswith("{{") and piece.endswith("}}"):
            p = templates[-1][1]
            out.append((p.get("1", "") + p.get("array", ""), p.get("2", ""), p.get("desc", "")))
        else:
            words = wiki_plain(piece).split()
            out.append((" ".join(words[:-1]), words[-1], "") if len(words) > 1 else (piece, "", ""))
    return out


def wiki_arg_types(args: str) -> list[str]:
    """Parameter types from a template's args, as wiki_args reads them."""
    return [t for t, _, _ in wiki_args(args)]


def _filled(text: str) -> str:
    """The text of a description, or empty when it is a placeholder."""
    text = re.sub(r"^\?\s*", "", text).strip()
    return "" if WIKI_PLACEHOLDER.match(text) else text


def wiki_docs(path: str | os.PathLike[str], syms: Symbols, report: Report) -> dict[str, Doc]:
    """Entries from the member templates on the API: pages of a wiki export."""
    out: dict[str, Doc] = {}
    for page in ET.parse(path).getroot().findall("m:page", WIKI_NS):
        title = page.findtext("m:title", "", WIKI_NS)
        if not title.startswith("API:"):
            continue
        report.stats["wiki: API pages"] += 1
        text = page.findtext("m:revision/m:text", "", WIKI_NS)
        # MediaWiki would read <T> as an HTML tag, so pages write type
        # arguments as the references &#x3008; and &#x3009; (CJK angle brackets).
        text = text.replace("&#x3008;", "<").replace("&#x3009;", ">")
        # LaTeX is indifferent to a space between braces, and without one a
        # formula's "}}" would close the template it sits in.
        text = MATH.sub(lambda m: m[1] + re.sub(r"([{}])(?=[{}])", r"\1 ", m[2]) + m[3], text)
        edited = page.findtext("m:revision/m:timestamp", "", WIKI_NS)[:10]
        source = f"Source: KSP wiki page {escape(title)}, last edited {edited}."
        # Pages may name their namespace with a {{Namespace:KSP.IO}} template.
        ns = re.search(r"\{\{Namespace:([\w.]+)\}\}", text)
        t = syms.types.get(norm(f"{ns.group(1)}.{title[4:]}")) if ns else syms.find_type(title[4:])
        if t is None:
            report.stats["wiki: pages with no matching 1.12.5 type"] += 1
            report.unmatched.append(("wiki", "page title names no type", title))
            continue
        for name, p in wiki_templates(text):
            if name == "Class" and _filled(p.get("summary", "")):
                d = Doc("wiki")
                d.summary = wiki_text(_filled(p["summary"]))
                d.remarks.append(source)
                report.stats["wiki: type summaries"] += 1
                if t["id"] in out:
                    report.stats["wiki: entries for a symbol already documented by this source"] += 1
                else:
                    out[t["id"]] = d
                continue
            if name not in WIKI_KINDS:
                continue
            report.stats["wiki: entries"] += 1
            desc = _filled(p.get("desc", ""))
            if not desc:
                report.stats["wiki: entries with no description"] += 1
                continue
            member, kind = p.get("name", "").strip().lstrip("."), WIKI_KINDS[name]
            arity: int | None = None
            ptypes: list[str] | None = None
            tparams: int | None = None
            parsed: list[tuple[str, str, str]] = []
            args = p.get("args", "")
            indexer = re.match(r"this\[(.*)\]$", member, re.S)
            generic = re.search(r"<(.*)>$", member)
            if indexer:
                member, kind, args = "this[]", "Property", str(indexer.group(1))
            elif generic:
                member = member[: generic.start()]
            if kind == "Method" and member == t["name"]:
                member = ".ctor"
            if kind == "Method" or indexer:
                parsed = wiki_args(args)
                ptypes = [ptype for ptype, _, _ in parsed]
                arity = len(ptypes)
            if kind == "Method":
                tparams = len(split_top(str(generic.group(1)))) if generic else 0
            sym, reason = syms.find_member(t["full"], member, kind, arity, ptypes, tparams)
            if sym is None:
                report.stats["wiki: entries with no unique 1.12.5 symbol"] += 1
                report.unmatched.append(
                    (
                        "wiki",
                        reason,
                        f"{t['full']}.{p.get('name', '')}"
                        + (f"({', '.join(ptypes or [])})" if kind == "Method" else ""),
                    )
                )
                continue
            d = Doc("wiki")
            d.summary = wiki_text(desc)
            pnames = sym["pnames"] or []
            for _, pname, pdesc in parsed:
                if pname in pnames and _filled(pdesc):
                    d.params[pname] = wiki_text(_filled(pdesc))
            if kind == "Method" and _filled(p.get("returndesc", "")):
                d.returns = wiki_text(_filled(p["returndesc"]))
            d.remarks.append(source)
            if sym["id"] in out:
                report.stats["wiki: entries for a symbol already documented by this source"] += 1
            else:
                out[sym["id"]] = d
    return out
