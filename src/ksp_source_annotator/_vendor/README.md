# Vendored packages

| Package | Version | License | Used for |
|---|---|---|---|
| [`game-install-finder`](https://github.com/beallio/game-install-finder) | 0.4.0 | MIT, in `game_install_finder/LICENSE` | Finding the KSP install in Steam, Heroic, and Lutris libraries |
| [`vdf`](https://github.com/ValvePython/vdf) | 3.4 | MIT, in `vdf/LICENSE` | Reading Steam's library files, for `game-install-finder` |

The files are copied unmodified from the packages' wheels, except that their imports of each other are rewritten to point inside `ksp_source_annotator._vendor`. They are excluded from `ruff` and `basedpyright`.

## Updating

Change the versions in `vendor.txt`, then run this from the repository root with the `dev` dependency group installed:

```sh
vendoring sync
```

It replaces everything here except `__init__.py`, this file, and `vendor.txt`, following `[tool.vendoring]` in `pyproject.toml`. Update the table above to match.

`ksp_source_annotator.install` calls `get_steam_path` and `build_installed_game_index` in `game_install_finder.cli`, and reads the `launcher`, `appid`, `name`, and `path` fields of the games it returns. That module is the package's command line, not a stable library API, so check those names after an update, and run the tests.
