# Native plugin ABI — version 1

V3NL 0.1.0 supports one native plugin format:

```
my_plugin/
  plugin.json
  my_plugin.dll
```

The launcher scans `%LOCALAPPDATA%\Victoria3NativeLoader\plugins`.
Plugins are **not enabled automatically**.

## Manifest

```json
{
  "schema_version": 1,
  "abi_version": 1,
  "id": "my-perf-plugin",
  "name": "My Performance Plugin",
  "version": "0.1.0",
  "dll": "my_plugin.dll",
  "dll_sha256": "ACTUAL_64_DIGIT_SHA256",
  "supported_game_sha256": ["PINNED_64_DIGIT_GAME_SHA256"],
  "dependencies": [],
  "init_export": "V3NL_PluginInit"
}
```

Run `Get-FileHash .\my_plugin.dll -Algorithm SHA256` and hash
the installed `victoria3.exe` before generating a real manifest.
The 64-character lowercase hash must be the file's actual value.
Do not reuse a version string alone: native RVA addresses change between builds.

IDs may contain lowercase letters, numbers, dot, dash, and underscore.
Dependencies are loaded first; missing dependencies or cycles prevent
the game from launching with the requested native plugin set.

## Export contract

Use `sdk/v3_native_plugin.h`:

```c
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include "v3_native_plugin.h"

BOOL WINAPI DllMain(HINSTANCE instance, DWORD why, LPVOID reserved) {
    if (why == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}

DWORD WINAPI V3NL_PluginInit(LPVOID reserved) {
    (void)reserved;
    // Validate game readiness and exact native signatures here.
    // Create your hooks carefully; do not suppress gameplay by default.
    return ERROR_SUCCESS;  // 0 means initialized
}
```

- Build a native x64 DLL.
- `V3NL_PluginInit` must be an **unmangled** exported symbol.
- The loader uses `LoadLibraryW` in a remote thread to load the DLL
  into the just-started Victoria 3 process; then it invokes the exported
  function through a second remote thread.
- Its argument is always `NULL` in ABI v1.
- Return 0 for success; nonzero marks failure. Avoid blocking: a 30-second
  timeout is enforced. Initialization may occur before the game's main menu.
- Do not implement complex operations, sleeps, hooks, or DLL loads inside
  `DllMain`; Windows loader lock restrictions apply.
- No inter-plugin shared memory or hot reload is promised in ABI v1.
- Plugin shutdown happens when the game process exits, not through
  an unload/reload mechanism.

## Versioning and plugins

The plugin manifest SHA is checked **before the game is launched**.
After injection, the real DLL load base is obtained from Windows' target
module enumeration. The ABI export RVA is read from the DLL's PE export
table, and the initialization thread is started at that address.

Each plugin should separately verify every native function signature it
patches. An EXE hash allowlist alone does not establish correctness.

## Suggested performance plugin pipeline

1. Reproduce slow simulation behavior under an unmodified full world.
2. Map native function/caller identities from independent evidence.
3. Add observational counters without changing gameplay.
4. Establish elapsed critical-path CPU/wait time; do not confuse counter
   frequency with elapsed time.
5. Implement exactly one reversible scheduler optimization, gated to
   the correct executable build.
6. Compare uninstrumented A/B simulation speed and world-state parity.
7. Keep diagnostics and candidate optimization separately switchable.

**Do not ship an adaptive queue/sleep plugin until steps 4–6 pass.**
The current 1337 investigation found hundreds of millions of empty
queue-helper return values; that is an important lead, not proof that
sleeps or scheduler patches are safe or faster.
