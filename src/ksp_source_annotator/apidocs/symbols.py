"""The symbols of the installed assemblies, as listed by symdump."""

from __future__ import annotations

import collections
import json
import os
import re
from pathlib import Path
from typing import TypedDict, cast


class Symbol(TypedDict):
    """One row of symbols.json, as written by symdump."""

    id: str
    asm: str
    kind: str
    mkind: str | None
    name: str
    type: str
    full: str
    ptypes: list[str] | None
    pnames: list[str] | None
    prefs: list[str] | None
    tparams: int | None
    acc: str
    loc: list[list[str]] | None


def norm(s: str) -> str:
    """Remove all whitespace, so names written with different spacing compare equal."""
    return re.sub(r"\s+", "", s)


def split_top(s: str, sep: str = ",", opens: str = "<([{", closes: str = ">)]}") -> list[str]:
    """Split on sep, ignoring separators nested inside brackets."""
    parts: list[str] = []
    depth, cur = 0, ""
    for ch in s:
        if ch in opens:
            depth += 1
        elif ch in closes:
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


CLR_ALIASES = {
    "Boolean": "bool",
    "Byte": "byte",
    "SByte": "sbyte",
    "Char": "char",
    "Int16": "short",
    "UInt16": "ushort",
    "Int32": "int",
    "UInt32": "uint",
    "Int64": "long",
    "UInt64": "ulong",
    "Single": "float",
    "Double": "double",
    "Decimal": "decimal",
    "String": "string",
    "Object": "object",
}
"""CLR type names and the C# keywords that mean the same type."""

CLR_ALIAS_RE = re.compile(r"\b(" + "|".join(CLR_ALIASES) + r")\b")
"""Matches any CLR_ALIASES name as a whole word."""


def canon_type(t: str) -> str:
    """A type name reduced to a form the sources agree on: no whitespace, no
    namespace or outer-type qualifiers, C# keywords for CLR names."""
    t = norm(t).replace("{", "<").replace("}", ">").rstrip("@&")
    t = re.sub(r"(?:\w+\.)+(?=\w)", "", t)
    return CLR_ALIAS_RE.sub(lambda m: CLR_ALIASES[str(m.group(1))], t)


def _in_scope(written: str, actual: str, scope: str) -> bool:
    """True when a parameter type written as written, inside the type scope,
    names actual: the same text, or a type nested in scope or in one of the
    types enclosing it, such as Gender for Outer.Gender inside Outer.Inner."""
    if written == actual:
        return True
    if not actual.endswith("." + written):
        return False
    qualifier = actual[: -len(written) - 1]
    parts = scope.split(".")
    enclosing = (".".join(parts[:i]) for i in range(len(parts), 0, -1))
    return any(e == qualifier or e.endswith("." + qualifier) for e in enclosing)


class Symbols:
    """Every symbol in the dumped assemblies, indexed for lookup by ID, type
    name, and member name."""

    def __init__(self, rows: list[Symbol]) -> None:
        self.all: list[Symbol] = rows
        self.by_id: dict[str, Symbol] = {s["id"]: s for s in self.all}
        self.types: dict[str, Symbol] = {}
        self.members: dict[tuple[str, str], list[Symbol]] = collections.defaultdict(list)
        # by name without the interface
        self.explicit: dict[tuple[str, str], list[Symbol]] = collections.defaultdict(list)
        # by lowercased name
        self.folded: dict[tuple[str, str], list[Symbol]] = collections.defaultdict(list)
        for s in self.all:
            if s["kind"] == "NamedType":
                self.types[norm(s["full"])] = s
            t, name = norm(s["type"]), s["name"]
            self.members[(t, name)].append(s)
            if "." in name and not name.startswith("."):
                self.explicit[(t, name.rsplit(".", 1)[1])].append(s)
            self.folded[(t, name.lower())].append(s)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Symbols:
        """Read the symbols.json that "symdump dump" writes."""
        with Path(path).open(encoding="utf-8") as f:
            return cls(cast("list[Symbol]", json.load(f)))

    def candidates(self, type_full: str, name: str) -> list[Symbol]:
        """Members with this name: exact, else explicit interface
        implementations (IFoo.Bar for Bar), else ignoring case."""
        t = norm(type_full)
        return self.members.get((t, name)) or self.explicit.get((t, name)) or self.folded.get((t, name.lower())) or []

    def find_type(self, name: str) -> Symbol | None:
        """Exact full name, else a unique type whose full name ends with it."""
        name = norm(name)
        if name in self.types:
            return self.types[name]
        hits = [s for full, s in self.types.items() if full.endswith("." + name)]
        return hits[0] if len(hits) == 1 else None

    def find_member(
        self,
        type_full: str,
        name: str,
        kind: str | None = None,
        arity: int | None = None,
        ptypes: list[str] | None = None,
        tparams: int | None = None,
        prefs: list[str] | None = None,
    ) -> tuple[Symbol | None, str]:
        """The one member that fits, or None with a short reason it does not,
        for Report.unmatched. Each filter is applied only while several candidates
        remain: kind, parameter count, generic parameter count, parameter
        types, then ref/out modifiers."""
        cand = self.candidates(type_full, name)
        named = len(cand)
        if named == 0:
            return None, "type exists, no member with this name"
        if len(cand) > 1 and kind:
            cand = [s for s in cand if s["kind"] == kind] or cand
        if len(cand) > 1 and arity is not None:
            cand = [s for s in cand if s["ptypes"] is not None and len(s["ptypes"]) == arity]
        if len(cand) > 1 and tparams is not None:
            cand = [s for s in cand if (s["tparams"] or 0) == tparams]
        if len(cand) > 1 and ptypes is not None:
            # Types as written first, then as C# would resolve an unqualified
            # name inside the declaring type; qualifiers and aliases are only
            # stripped when neither singles one out.
            want = [norm(p) for p in ptypes]
            exact = [s for s in cand if [norm(p) for p in s["ptypes"] or []] == want]
            if len(exact) == 1:
                return exact[0], ""
            scope = norm(type_full)
            scoped = [
                s
                for s in cand
                if len(s["ptypes"] or []) == len(want)
                and all(_in_scope(w, norm(a), scope) for w, a in zip(want, s["ptypes"] or [], strict=True))
            ]
            if len(scoped) == 1:
                return scoped[0], ""
            want = [canon_type(p) for p in ptypes]
            cand = [s for s in cand if [canon_type(p) for p in s["ptypes"] or []] == want]
        if len(cand) > 1 and prefs is not None:
            cand = [s for s in cand if s["prefs"] == prefs]
        if len(cand) == 1:
            return cand[0], ""
        if not cand:
            return None, f"{named} members with this name, none fits the signature"
        return None, f"{named} members with this name, {len(cand)} fit the signature equally"
