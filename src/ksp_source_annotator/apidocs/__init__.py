"""Building .NET XML documentation files for the game's assemblies.

build_apidocs is the whole step. merge_docs is the part of it that needs no
.NET tooling: given a symbols.json and the sources, it writes the XML files.
"""

from .build import ASSEMBLIES, build_apidocs, fetch_sources
from .doc import Doc, Report
from .merge import merge_docs
from .symbols import Symbol, Symbols

__all__ = [
    "ASSEMBLIES",
    "Doc",
    "Report",
    "Symbol",
    "Symbols",
    "build_apidocs",
    "fetch_sources",
    "merge_docs",
]
