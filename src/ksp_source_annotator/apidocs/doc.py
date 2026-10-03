"""One documentation entry, and the record of what a merge did."""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from xml.sax.saxutils import quoteattr

SOURCES = ("official", "anatid", "wiki", "game")
"""Source names in priority order: an earlier source's entry for a symbol wins."""

STEPS = (
    # What was read.
    "unparseable files",
    "API pages",
    "pages with no matching 1.12.5 type",
    "entries",
    "documented types",
    "documented members",
    "documented enums",
    "documented enum values",
    "localization keys on symbols",
    # What did not lead to a symbol.
    "entries with no description",
    "types with no unique 1.12.5 symbol",
    "members with no unique 1.12.5 symbol",
    "enums with no unique 1.12.5 symbol",
    "enum values with no unique 1.12.5 symbol",
    "entries with no unique 1.12.5 symbol",
    "keys with no en-us string",
    "entries with no text",
    "entries for a symbol already documented by this source",
    # What did, and how.
    "entries remapped to a moved or changed symbol",
    "type summaries",
    "symbols with a tooltip",
    "symbols with only a label",
    # The merge.
    "entries dropped as malformed",
    "symbols documented",
    "already documented by a higher-priority source",
    "entries written",
)
"""Report descriptions in the order the steps they count are applied: what a
source read, what was lost on the way to a symbol, what was found, and then
what the merge kept. Each source uses the ones that apply to it."""


@dataclass
class Report:
    """What happened to the entries of each source during a merge."""

    stats: collections.Counter[str] = field(default_factory=collections.Counter)
    """Counts of what happened to entries, keyed "<source>: <description>",
    or "output: <description>" for the files written."""
    unmatched: list[tuple[str, str, str]] = field(default_factory=list)
    """(source, reason, entry) for every documented entry that found no symbol."""

    def format(self) -> str:
        """The counts, one per line: sources in priority order, each in the
        order of STEPS, then the output. This is REPORT.txt."""
        groups = (*SOURCES, "output")

        def key(item: tuple[str, int]) -> tuple[int, int, str]:
            group, _, step = item[0].partition(": ")
            return (
                groups.index(group) if group in groups else len(groups),
                STEPS.index(step) if step in STEPS else len(STEPS),
                item[0],
            )

        return "\n".join(f"{v:7d}  {k}" for k, v in sorted(self.stats.items(), key=key))


class Doc:
    """One <member> entry. Fields hold already-escaped inner XML."""

    def __init__(self, source: str) -> None:
        self.source: str = source
        self.summary: str = ""
        self.params: dict[str, str] = {}
        self.typeparams: dict[str, str] = {}
        self.returns: str = ""
        self.remarks: list[str] = []
        # verbatim inner XML, used instead of the fields above
        self.raw: str | None = None

    def empty(self) -> bool:
        """True when there is nothing to write for this entry."""
        if self.raw is not None:
            return not self.raw.strip()
        return not (self.summary or self.params or self.typeparams or self.returns or self.remarks)

    def render(self) -> str:
        """The inner XML of the <member> element."""
        if self.raw is not None:
            return self.raw
        out: list[str] = []
        if self.summary:
            out.append(f"<summary>{self.summary}</summary>")
        for n, d in self.typeparams.items():
            out.append(f"<typeparam name={quoteattr(n)}>{d}</typeparam>")
        for n, d in self.params.items():
            out.append(f"<param name={quoteattr(n)}>{d}</param>")
        if self.returns:
            out.append(f"<returns>{self.returns}</returns>")
        for r in self.remarks:
            out.append(f"<remarks>{r}</remarks>")
        return "".join(out)
