# Victoria 3 Native Loader — developer contract

Follow the host project's game-process and user-authorization rules before
any native runtime testing. Do not bypass this repository's safety gates.

## Required performance-plugin workflow

**All new native performance hooks MUST be developed as V3NL ABI v1 plugins from the start.**
No standalone injector or alternate Victoria 3 process-launching codepath.

1. Source belongs in its own independent native plugin directory, not inside
   the public launcher core.
2. Export `DWORD WINAPI V3NL_PluginInit(LPVOID)`; DllMain must remain minimal.
3. Pin the exact game executable SHA256, compiled DLL SHA256 and the bytes at
   each native hook site; incompatible targets must fail closed.
4. Create a bounded developer trial manifest as documented in
   `docs/PERFORMANCE_TEST_CONTRACT.md`.
5. Build the DLL before testing. The experiment runner stages and validates
   the compiled artifact.
6. Both control and candidate game sessions MUST be started using
   `v3nl.launcher.launch_game()`, not a separate process runner,
   external injection script or manually attached Frida injector.
7. Keep the game build, world, mod load order, starting conditions and
   original calculations identical between arms unless explicitly authorized
   as a separate, fidelity-changing experiment.
8. Never suspend or resume any Windows process or thread, including during
   hook installation. Do not manipulate unrelated game instances.
9. Run only when explicitly authorized in the current user conversation;
   a ready manifest by itself is NOT permission to launch Victoria 3.
10. Validate plugin initialization, crash-free simulation, matched-day timing,
    and state parity before accepting any speed improvement. Call counts and
    scheduler sampling alone do not prove a performance gain.

## Offline planning and explicit run commands

`python run.py --native-experiment path\to\experiment.json --dry-run`

`python run.py --native-experiment path\to\experiment.json --execute`

Only the second command builds or starts a game; use it only with explicit
current authorization. The launcher must remain usable with zero plugins.
