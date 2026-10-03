"""The ksp-source-annotator command."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap
from collections.abc import Sequence

from . import __version__
from .annotate import annotate_source
from .apidocs import build_apidocs
from .decompile import decompile
from .errors import KspSourceAnnotatorError
from .install import ENV_VAR, KspInstall
from .link import link_apidocs, unlink_apidocs
from .pipeline import run_all
from .workspace import Workspace, user_cache_dir

DESCRIPTION = """\
Turn a Kerbal Space Program install into a browsable C# source tree with
documentation comments, plus XML documentation files that give IDE tooltips
in mod projects.

Output goes to KSP-<version>/ in the working directory. The KSP install is
only read, except by the link command. The output is for private reference;
the game's terms do not permit redistributing it.
"""

ENVIRONMENT = """\
environment variables:
  KSP_ROOT    Root of the KSP install (the directory holding KSP_Data/ and
              GameData/), used when --ksp-dir is not given. This is the
              variable that KSPBuildTools reads.

With neither --ksp-dir nor KSP_ROOT, the install is looked for in the Steam,
Heroic, and Lutris libraries on this machine.
"""

WIKI_HELP = """\
getting the wiki export (a browser is needed; the wiki blocks scripted
requests):
  1. Open https://wiki.kerbalspaceprogram.com/wiki/Special:Export
  2. In "Add pages from category", enter "Community API Documentation" and
     press Add. The page list fills with the API: pages.
  3. Do the same for its subcategory "KSP.IO Namespace". Adding a category
     does not include the pages of its subcategories.
  4. Leave "Include only the current revision, not the full history" checked
     and "Save as file" checked, then press Export.
  5. Move the downloaded Kerbal+Space+Program+Wiki-<timestamp>.xml into the
     working directory, or pass its path with --wiki.
  Only pages titled "API:<type name>" are read; others are ignored.
"""

WIKI_OPTION = (
    "MediaWiki XML export to use as a documentation source. Default: the "
    "Kerbal+Space+Program+Wiki-*.xml in the working directory with the latest "
    "timestamp in its name; if there is none, the wiki source is skipped."
)


class Args(argparse.Namespace):
    """The command-line arguments, typed."""

    command: str = ""
    ksp_dir: str | None = None
    work_dir: str | None = None
    wiki: str | None = None
    link: bool = False
    force: bool = False
    version_dir: str | None = None
    cache_dir: str | None = None
    cache: bool = False


def build_parser() -> argparse.ArgumentParser:
    """The argument parser for the command and its subcommands."""
    raw = argparse.RawDescriptionHelpFormatter
    common = argparse.ArgumentParser(add_help=False)
    _ = common.add_argument(
        "--ksp-dir",
        metavar="DIR",
        help="root of the KSP install (the directory holding KSP_Data/ and "
        "GameData/); default: $KSP_ROOT, then a search of the game "
        "launcher libraries",
    )
    _ = common.add_argument(
        "--work-dir", metavar="DIR", help="directory for output and wiki exports; default: the current directory"
    )
    _ = common.add_argument(
        "--cache-dir",
        metavar="DIR",
        help=f"directory for built tools and downloaded documentation, which any number of "
        f"working directories can share; default: {user_cache_dir()}",
    )

    parser = argparse.ArgumentParser(
        prog="ksp-source-annotator", description=DESCRIPTION, epilog=ENVIRONMENT, formatter_class=raw
    )
    _ = parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    def command(name: str, summary: str, description: str, epilog: str = ENVIRONMENT) -> argparse.ArgumentParser:
        # Wrap the paragraphs; lines of a list are already laid out.
        description = "\n".join(
            line if line.startswith(" ") else textwrap.fill(line, 78) for line in description.split("\n")
        )
        return sub.add_parser(
            name, parents=[common], help=summary, description=description, epilog=epilog, formatter_class=raw
        )

    p = command(
        "all",
        "run decompile, apidocs, and annotate in order",
        "Run the decompile, apidocs, and annotate steps in order. The decompile step "
        "skips de4dot and ilspycmd when their output is newer than their input and "
        "this package's files.",
        WIKI_HELP + "\n" + ENVIRONMENT,
    )
    _ = p.add_argument("--wiki", metavar="FILE", help=WIKI_OPTION)
    _ = p.add_argument(
        "--force",
        action="store_true",
        help="run de4dot and ilspycmd even when their output is newer than their "
        "input and this package's files; without this each is skipped when its "
        "output is up to date",
    )
    _ = p.add_argument(
        "--link", action="store_true", help="also run the link step, which writes symlinks into the KSP install"
    )

    p = command(
        "decompile",
        "decompile the game assemblies into C# projects",
        "Decompile KSP's managed game assemblies into KSP-<version>/: de4dot strips the "
        "Crypto Obfuscator control flow from Assembly-CSharp, then ilspycmd exports each "
        "assembly as a C# project. Each tool is skipped when its output is newer than "
        "its input and this package's files. A project that is exported again loses its /// comments until the "
        "annotate step runs again.\n\n"
        "Requires dotnet on PATH. An ilspycmd or de4dot on PATH is used if there is one. "
        'Otherwise ilspycmd is installed with "dotnet tool install" (it needs the .NET 10 '
        "runtime) and de4dot is "
        "downloaded and built from source, both into the cache on first run.",
    )
    _ = p.add_argument(
        "--force",
        action="store_true",
        help="run de4dot and ilspycmd even when their output is newer than their "
        "input and this package's files; without this each is skipped when its "
        "output is up to date",
    )

    p = command(
        "apidocs",
        "build XML documentation files for the game assemblies",
        "Build .NET XML documentation files for KSP's game assemblies into "
        "KSP-<version>/apidocs/, merged from (in priority order):\n"
        "  1. the official Doxygen XML package (KSP 1.12.4, from the Wayback Machine)\n"
        "  2. anatid's community Assembly-CSharp.xml\n"
        "  3. a MediaWiki export of the KSP wiki's API: namespace, if one is available\n"
        "  4. the game's own en-us UI text, for symbols whose attributes carry\n"
        "     localization keys\n\n"
        "Requires dotnet on PATH. Sources 1 and 2 are downloaded into the cache on first "
        "run.",
        WIKI_HELP + "\n" + ENVIRONMENT,
    )
    _ = p.add_argument("--wiki", metavar="FILE", help=WIKI_OPTION)

    p = command(
        "annotate",
        "write the documentation into the source as /// comments",
        "Write the merged API documentation into the decompiled source as /// comments, "
        "in place. Run after decompile and apidocs. Re-running replaces the comments "
        "written by an earlier run.\n\nRequires dotnet on PATH.",
    )
    _ = p.add_argument(
        "version_dir",
        nargs="?",
        metavar="VERSION_DIR",
        help="the KSP-<version> directory to annotate; default: the one in the "
        "working directory for the install's version",
    )

    _ = command(
        "link",
        "symlink the XML documentation into the KSP install",
        "Symlink the XML documentation files built by apidocs into the KSP install, "
        "beside the assemblies they describe, so that language servers show them for "
        "projects that reference those assemblies. Existing symlinks are updated. A "
        "regular file with the same name is left alone and reported.\n\n"
        "This and clean are the only commands that write to the KSP install.",
    )

    p = sub.add_parser(
        "clean",
        parents=[common],
        formatter_class=raw,
        help="remove everything generated, and with --cache everything downloaded",
        description=textwrap.fill(
            "Remove the KSP-<version>/ directories from the working directory, and "
            "the symlinks that the link command made to them in the KSP install. With "
            "--cache, also remove the tools and downloads in the cache directory. Wiki "
            "exports are inputs and are kept. Other files in the install, including "
            "symlinks to anywhere else, are not touched. When no install is given and "
            "none is found, the install is skipped.",
            78,
        ),
    )
    _ = p.add_argument(
        "--cache",
        action="store_true",
        help="also remove the built tools and downloaded documentation from the cache directory",
    )
    return parser


def _install_to_clean(ksp_dir: str | None) -> KspInstall | None:
    """The install whose links clean removes: the one named, or else the one
    found, or None with a note when none is found."""
    if ksp_dir or os.environ.get(ENV_VAR):
        return KspInstall.locate(ksp_dir)
    try:
        return KspInstall.locate()
    except KspSourceAnnotatorError as e:
        logging.getLogger(__name__).info("note: not removing links from a KSP install (%s)", e)
        return None


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; returns the process exit status."""
    args = build_parser().parse_args(argv, namespace=Args())
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    try:
        workspace = Workspace.at(args.work_dir, args.cache_dir)
        if args.command == "clean":
            install = _install_to_clean(args.ksp_dir)
            removed = unlink_apidocs(install, workspace) if install else []
            for path in [*removed, *workspace.clean(cache=args.cache)]:
                print(f"removed {path}")
            return 0
        install = KspInstall.locate(args.ksp_dir)
        match args.command:
            case "all":
                _ = run_all(install, workspace, wiki=args.wiki, force=args.force, link=args.link)
            case "decompile":
                _ = decompile(install, workspace, force=args.force)
            case "apidocs":
                _ = build_apidocs(install, workspace, wiki=args.wiki)
            case "annotate":
                _ = annotate_source(install, workspace, args.version_dir)
            case "link":
                _ = link_apidocs(install, workspace)
            case _:
                raise AssertionError(args.command)
    except KspSourceAnnotatorError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
