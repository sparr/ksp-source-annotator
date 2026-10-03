"""Decompile a Kerbal Space Program install into documented C# source.

Each step is a function taking the install to read and the workspace to
write into:

    from ksp_source_annotator import KspInstall, Workspace, run_all

    install = KspInstall.locate("/path/to/Kerbal Space Program")
    workspace = Workspace.at("/path/to/output")
    run_all(install, workspace)

run_all calls decompile, build_apidocs, and annotate_source in that order.
link_apidocs and unlink_apidocs are the only functions that write to
the install. Progress is
reported through the logging module, under the "ksp_source_annotator" logger.
"""

from importlib.metadata import PackageNotFoundError, version

from .annotate import annotate_source
from .apidocs import Report, build_apidocs, merge_docs
from .decompile import decompile
from .errors import KspSourceAnnotatorError
from .install import KspInstall, KspVersion, find_installs
from .link import link_apidocs, unlink_apidocs
from .pipeline import run_all
from .workspace import Workspace

try:
    __version__ = version("ksp-source-annotator")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0+unknown"

__all__ = [
    "KspInstall",
    "KspSourceAnnotatorError",
    "KspVersion",
    "Report",
    "Workspace",
    "__version__",
    "annotate_source",
    "build_apidocs",
    "decompile",
    "find_installs",
    "link_apidocs",
    "merge_docs",
    "run_all",
    "unlink_apidocs",
]
