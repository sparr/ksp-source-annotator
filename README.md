# KSP Decompiled Source Annotator

A Python package that turns a Kerbal Space Program install into a browsable C# source tree with documentation comments, plus XML documentation files that give IDE tooltips in mod projects.

## Legal Warning

The output of this tool is only for your private reference regarding your own installation of KSP. The game's terms do not permit redistributing decompiled source, so do not publish the `KSP-*` directories.

## Requirements

* Python 3.12 or later
* `dotnet` SDK 10 or later, or SDK 8 or later if `ilspycmd` is already on your PATH
* `ilspycmd`, optional: version 11.1.0.9782 is installed locally if none is on your PATH, and it needs the .NET 10 runtime
* `de4dot`, optional: downloaded and built from source if not on your PATH

The helpers this package builds target .NET 8 and run on any newer runtime.

Currently only confirmed working on Linux. The Windows and macOS install layouts are recognized, but untested; feedback is welcome! On Windows, the `link` step needs permission to create symlinks, which Developer Mode grants.

## Installing

```sh
pip install ksp-source-annotator
```

or, from a checkout of this repository, `pip install .` (add `-e` to work on the code).

## Running from a checkout

The package has no required Python dependencies, so it also runs from a checkout of this repository without being installed. From the repository root, put `src/` on the module path and run the package as a module:

```sh
PYTHONPATH=src python3 -m ksp_source_annotator all
```

Wherever the sections below say `ksp-source-annotator`, use `PYTHONPATH=src python3 -m ksp_source_annotator` instead.

## Normal use

Run everything from the directory that should hold the output, naming the game install with `--ksp-dir` unless it can be found for you (see below):

```sh
ksp-source-annotator all --ksp-dir "/path/to/Kerbal Space Program"
```

That runs the first three steps below in order. Running it again only redoes work whose input changed: `de4dot` and `ilspycmd` are skipped when their output is newer than both their input and this package's own files (so updating or editing the package redoes them), unless you pass `--force`. Each step is also a command of its own, taking the same `--ksp-dir`:

```sh
ksp-source-annotator decompile
ksp-source-annotator apidocs
ksp-source-annotator annotate
ksp-source-annotator link
```

`ksp-source-annotator clean` removes the output directories, only those named like `KSP-1.12.5.3190`, and the symlinks that `link` made to them in the game install. `clean --cache` also removes the built tools and downloaded documentation from the cache directory. The wiki export is always kept. It finds the install the same way the other commands do; when there is none to find, it cleans only the working directory. `python -m ksp_source_annotator` is the same command.

Every command except `clean` needs the game install, the directory holding `KSP_Data/` and `GameData/`. It is taken from the first of these that applies:

1. `--ksp-dir DIR`.
2. The `KSP_ROOT` environment variable, which is the variable that KSPBuildTools reads.
3. A search of the Steam, Heroic, and Lutris libraries on this machine. It reads only launcher metadata on disk, and stops with a list if it finds more than one KSP install.

 Every command also takes `--work-dir DIR` to use a directory other than the current one, and `--cache-dir DIR` to use a cache directory other than the default. Each command documents its options in `--help`.

Your KSP install is only read unless you run `ksp-source-annotator link` (or `ksp-source-annotator all --link`) to symlink the results beside the game DLLs, or `ksp-source-annotator clean` to remove those symlinks. Output goes to a directory named for the game version, such as `KSP-1.12.5.3190/`, in the working directory. Tools that get built or installed, and downloaded documentation sources, go to a cache directory that every working directory shares:

| OS | Default cache directory |
|---|---|
| Linux | `$XDG_CACHE_HOME/ksp-source-annotator`, by default `~/.cache/ksp-source-annotator` |
| macOS | `~/Library/Caches/ksp-source-annotator` |
| Windows | `%LOCALAPPDATA%\ksp-source-annotator\Cache` |

## What each step does

1. `decompile` removes the obfuscation from `Assembly-CSharp.dll` with `de4dot`, then exports `Assembly-CSharp` and `KSPAssets` as C# projects with `ilspycmd`.
2. `apidocs` merges API documentation from four sources and writes it as .NET XML documentation files. When two sources document the same symbol, the earlier one in this list wins:
   1. Squad's official Doxygen documentation for KSP 1.12.4.
   2. anatid's community `Assembly-CSharp.xml`.
   3. The KSP wiki's `API:` pages, from a manual export (see below).
   4. The game's own English UI text, for fields and methods that carry tooltips or labels.
3. `annotate` writes that documentation into the decompiled source as `///` comments.
4. `link` symlinks the XML files beside the DLL files in your game directory.

## Output

| Path under `KSP-<version>/` | Contents |
|---|---|
| `Assembly-CSharp/` | Decompiled game source with documentation comments, and a `.csproj` |
| `KSPAssets/` | Decompiled source of the small asset-loading assembly |
| `apidocs/Assembly-CSharp.xml` | Documentation for `Assembly-CSharp.dll` |
| `apidocs/Assembly-CSharp-firstpass.xml` | Documentation for `Assembly-CSharp-firstpass.dll` |
| `apidocs/REPORT.txt` | Entry counts per source |
| `apidocs/UNMATCHED.txt` | Source entries that matched no symbol |
| `deobfuscated/` | The cleaned `Assembly-CSharp.dll` that was decompiled |
| `VERSION.txt` | Game version and tool versions used |

## Using the results

**Reading the game's code.** Open a `.cs` file under `KSP-<version>/Assembly-CSharp/` in an editor with C# support and let it load `Assembly-CSharp.csproj`. Go-to-definition, find-references, and hover documentation then work across the game code.

**Tooltips in mod projects.** A language server shows the XML documentation when `Assembly-CSharp.xml` sits beside the `Assembly-CSharp.dll` that the project references. `ksp-source-annotator link` symlinks the files from `apidocs/` into the install's `KSP_Data/Managed/`, creating or updating the links. It and `clean`, which removes the links, are the only commands that write to the game install. For a project that references assemblies somewhere else, symlink or copy the files there by hand.

## Wiki export

The wiki blocks scripted downloads, so its pages have to be exported by hand in a browser:

1. Open https://wiki.kerbalspaceprogram.com/wiki/Special:Export
2. In "Add pages from category", enter "Community API Documentation" and
   press Add. The page list fills with the API: pages.
3. Do the same for its subcategory "KSP.IO Namespace". Adding a category
   does not include the pages of its subcategories.
4. Leave "Include only the current revision, not the full history" checked
   and "Save as file" checked, then press Export.
5. Move the downloaded Kerbal+Space+Program+Wiki-<timestamp>.xml into the
   working directory, or pass its path with --wiki.


## After a game update

Run `ksp-source-annotator all` again. A new version gets its own `KSP-<version>/` directory, and the old one is left alone.

## Using it from Python

Each step is a function that takes the install to read and the workspace to write into:

```python
from ksp_source_annotator import KspInstall, Workspace, annotate_source, build_apidocs, decompile, run_all

install = KspInstall.locate("/path/to/Kerbal Space Program")  # or locate() for KSP_ROOT or a launcher library
workspace = Workspace.at("/path/to/output")

run_all(install, workspace)  # all three steps

out = decompile(install, workspace)  # or one at a time
report = build_apidocs(install, workspace)
annotate_source(install, workspace)
```

`link_apidocs` is the fourth step, and `unlink_apidocs` undoes it. Failures raise `KspSourceAnnotatorError`. Progress is reported through the `logging` module under the `ksp_source_annotator` logger, so nothing is printed unless the caller configures logging. `ksp_source_annotator.apidocs.merge_docs` is the documentation merge on its own; it needs no .NET tooling, only a symbol list and the source files.

## Layout of this repository

| Path | Contents |
|---|---|
| [`src/ksp_source_annotator/`](https://github.com/sparr/ksp-source-annotator/tree/main/src/ksp_source_annotator) | The package: one module per step, plus [`cli.py`](https://github.com/sparr/ksp-source-annotator/blob/main/src/ksp_source_annotator/cli.py) |
| [`src/ksp_source_annotator/apidocs/`](https://github.com/sparr/ksp-source-annotator/tree/main/src/ksp_source_annotator/apidocs) | The documentation merge, one module per source |
| [`src/ksp_source_annotator/symdump/`](https://github.com/sparr/ksp-source-annotator/tree/main/src/ksp_source_annotator/symdump) | A C# helper built on Roslyn, compiled into the cache directory on first use |
| [`src/ksp_source_annotator/_vendor/`](https://github.com/sparr/ksp-source-annotator/tree/main/src/ksp_source_annotator/_vendor) | Copies of `game-install-finder` and `vdf`, each under its own MIT license, which find the KSP install in launcher libraries |
| [`tests/`](https://github.com/sparr/ksp-source-annotator/tree/main/tests) | `pytest` tests; none needs a KSP install, and the one that needs `dotnet` is skipped without it or with `-m "not dotnet"` |

`symdump` is C# instead of Python because Roslyn is more capable at C# symbol resolution than any Python package.

The launcher search is vendored instead of a dependency so that the package has no required dependencies and runs from a checkout. Its [`README.md`](https://github.com/sparr/ksp-source-annotator/blob/main/src/ksp_source_annotator/_vendor/README.md) says how to update it.

## AI Disclosure

This code was written approximately 95% by Claude Opus 5.5, 5% by a human. The code has been reviewed by multiple other LLMs. About 75% of the code has been subject to light-to-moderate human review, with the remaining mostly-not-human-reviewed 25% being the portions that interact with Roslyn and Mediawiki. Further review is warranted, planned, and welcome.