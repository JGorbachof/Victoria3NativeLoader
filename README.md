# Victoria 3 Native Loader (V3NL)

A modular, local Windows launcher for **Victoria 3** that imports Paradox launcher
playsets, preserves their mod load order, launches the game normally, and can
optionally load independently developed **native x64 DLL plugins**.

**Status: 0.1.0 developer preview.** No game optimization plugin is bundled
or enabled. Native plugin integration is experimental and must be validated
against each supported game build before regular use.

## Features

- Read installed mods and playsets from the actual Paradox
  `launcher-v2.sqlite` database **read-only**.
- Import a selected playset; add local mods; remove and reorder mods.
- Launch Victoria 3 with the chosen mod order through its supported
  `content_load.json` format.
- Managed profiles under
  `%LOCALAPPDATA%\Victoria3NativeLoader\profiles\<name>`.
- Optional links to the existing **shader cache** (helps avoid unnecessary
  shader recompilation) and **save games**, without copying or deleting them.
- Native DLL plugins in independently installable folders under
  `%LOCALAPPDATA%\Victoria3NativeLoader\plugins\<plugin-id>`.
- Explicit opt-in for native injection, per-plugin enable/disable and
  dependency ordering.
- Plugin SHA-256 checks, exact-game-executable hash allowlists, x64 PE
  validation, and a stable `V3NL_PluginInit` export.
- Uses normal `CreateProcess` startup and an in-process `LoadLibraryW`
  remote call after the game is running. **Never suspends the game process.**
- Distinct **Launch without DLLs** troubleshooting mode.
- A GitHub Actions workflow to test and package a portable Windows executable.

## Quick start on Windows

Requirements: 64-bit Windows 10/11, Python 3.11+, Victoria 3 installed.
For source execution, install `psutil` and `pefile`.

```powershell
cd Victoria3NativeLoader
python -m pip install -e .
python run.py
```

Or double-click `run.cmd` after installing dependencies. No game launch
occurs until the user clicks **Launch Victoria 3**.

### Using existing playsets

In **Play & Mods**, select a Paradox playset and click **Import playset**.
The right-hand side shows enabled mods in exact load order. Move mods up/down,
add custom folders, and click **Launch Victoria 3**. The launcher reads the
source database but does not modify it.

The managed profile is intentionally separate. Its `content_load.json`
holds the chosen loadout; the source mod folders remain unchanged. By
default the launcher links the normal save folder and shader cache into
the managed profile. Disable either option under **Game Settings**.

### Adding native plugins

1. Compile an x64 DLL exporting `DWORD WINAPI V3NL_PluginInit(void*)`.
2. Create `plugin.json` in the same folder containing the DLL filename,
   the DLL's SHA-256, and the compatible Victoria 3 EXE SHA-256 list.
3. Choose **Native Plugins → Install plugin folder** (or copy the folder
   under the local plugins directory).
4. Enable that plugin in the list and enable the master **native DLL injection**
   checkbox. Native injection is disabled by default.
5. Launch the game; the loader checks the plugin and starts it in the
   just-launched game process. A failure is shown in the log; the game isn't
   forcibly terminated by this launcher.

Read [Plugin SDK](docs/PLUGIN_API.md) and [Security](SECURITY.md) first.
The sample in [plugins/example_native](plugins/example_native) deliberately
does not patch the game.

## Development commands

```powershell
python -m compileall -q src
python -m unittest discover -s tests -v
python run.py --dry-run
python run.py --list-playsets
python run.py --dry-run --playset-id YOUR-PLAYSET-UUID
```

`--dry-run` never launches Victoria 3, never creates a game profile and
never injects a DLL. The graphical application also has **Preview launch**.

GitHub Actions builds `Victoria3NativeLoader.exe` for Windows on commits
or manual workflow dispatch. The repo does **not** need to commit a game
executable, Paradox assets, proprietary DLLs, credentials, or user settings.

## Compatibility and limitations

- Currently targets Victoria 3 on 64-bit Windows using the Paradox
  `launcher-v2.sqlite` playset tables and `content_load.json`.
- Installed mods in directories are supported. Mod archives that aren't
  directly readable as folders are not yet supported in manual selection.
- Native DLL plugins are x64 and **version-pinned** to game executable hashes.
  A game update requires explicit compatibility review.
- Plugin initialization runs after normal game startup and before the
  game necessarily reaches the main menu. Each plugin must account for
  engine initialization and wait for verified native readiness itself.
- Injecting a DLL doesn't make its optimization correct. Native game
  scheduler changes must be tested for crashes, deadlocks, tick timing,
  and game-state divergence.
- The launcher does not provide a persistent C++ bridge API, real-time
  plugin reload, or a downloader/marketplace in 0.1.0.
- The default game-process guard prevents accidental double launches.
  If a game is already running, close it before launching through V3NL.
- The game executable is launched directly. This has been the tested
  path for local 1337 runtime profiles, but Steam-specific services and
  third-party launcher extensions can behave differently.
- First-run UI is intentionally built with Windows-compatible Tk/ttk
  rather than a bundled browser framework; no web service is required.

## Source layout

```
src/v3nl/
  ui.py          GUI, playsets, mod ordering, plugin toggles
  mods.py        read-only launcher-v2.sqlite / local metadata
  profiles.py    content_load.json and managed game userdir
  config.py      per-user settings
  plugins.py     plugin manifests, dependency resolution, hash/PE checks
  win_inject.py  Win32 native DLL loader, owned-game-only guard
  launcher.py    launch planner, process start and session logs
sdk/             native ABI header
plugins/         example native C plugin source
tests/           offline test suite
.github/         Windows CI build
```

## Safety and ownership

V3NL is a community tool, **not affiliated with Paradox Interactive**.
It only loads plugins explicitly selected by the user. Source data and
Paradox playsets remain intact. Install only trusted native plugins:
DLL injection runs code with your permissions. See [SECURITY.md](SECURITY.md).

The repository is suitable for GitHub hosting, but uploading/publishing
it requires an explicit repository destination and visibility choice.
