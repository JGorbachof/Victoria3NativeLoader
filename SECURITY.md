# Security model

V3NL is a local, opt-in native DLL injector intended for Victoria 3 single-player modding.

**DLL plugins are arbitrary native code with your Windows user permissions inside the game process.**
There is no sandbox. Only install plugins you have personally reviewed and trust.

Each plugin manifest pins the DLL's SHA-256 and an allowlist of exact Victoria 3
executable hashes. This prevents accidental ABI mismatches and casual on-disk changes;
hashes are not authenticity signatures or malware protection.

There is no automatic plugin download, no marketplace, no browser-authentication integration,
no telemetry, and no automatic game-patching system. Plugins are disabled by default.
Use "Launch without DLLs" to troubleshoot.

The application creates its own game profile under Local AppData. It never edits
the Paradox playset database or the original game's executable.
Native injection may still crash or damage the current game's state. Back up saves
before enabling experimental plugins.

Plugin authors should never implement significant work in DllMain. Use
V3NL_PluginInit, check game version and function signatures, and avoid unsafe
thread suspension or blind byte patches.

Report reproducible security issues privately to the repository maintainer
when a repository is published.
