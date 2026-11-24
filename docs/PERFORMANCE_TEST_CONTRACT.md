# Performance hook development: V3NL-first standard

This contract applies to new native engine-performance experiments, especially
Terra Universalis Alpha 1337.

## Extreme-first triage before optimization

For the owner's Terra Universalis 1337 performance workstream, **screen a
subsystem with an extreme, single-variable probe BEFORE incremental tuning**.
Aim for roughly 10× less target-subsystem work, or a completely bypassed
*optional* gameplay callback if a safe, documented diagnostic-only short-circuit
exists. Rank by measured reduction in actual complete-day simulation time, NOT
by hook-call reductions alone. Maintain an evidence register even for zero-effect,
invalid, or blocked probes.

A startup/scheduler/queue core function must NOT be disabled in an attempt to
force a large signal: skipped job servicing, missing producer wakeups, and held
locks make the result an invalid deadlock rather than a benchmark. Map safety
and verify a no-suspension hook installation method first. Where a safe extreme
cannot be achieved, mark that target BLOCKED and try a different subsystem.

AI/journal/investment bypass trials that intentionally change game outcomes are
**DISPOSABLE_DIAGNOSTIC_NONPARITY** tests, not release candidates. Keep the
baseline intact and separately label world divergence. After screening all
testable candidates, optionally run a **combined extreme stress trial** only
with individually safe, compatible probes; label it research-only and do not
assume its outcomes are valid gameplay. Then develop independently validated,
*correctness-preserving* optimized plugins for the biggest real bottlenecks.
Enable these tuned winners together through this launcher in a separate
release-quality A/B with leave-one-out ablations for overlapping improvements.

The TU-specific screening matrix and result registry are maintained in the
owner's local performance research workstream, separately from this generic
public launcher.

## Workflow

- **Build:** Compile a dedicated x64 DLL from a standalone source directory.
  Use the exported `V3NL_PluginInit` interface, currently ABI v1.
  Do not modify the original game executable or DLL files on disk.
- **Validate:** Before the game starts, check the exact game-executable hash,
  DLL hash, PE architecture, entrypoint export, dependency graph and every
  target native function's signature. Fail closed if incompatible.
- **Stage:** A local developer build goes to the launcher's
  `%LOCALAPPDATA%\Victoria3NativeLoader\plugins\<plugin-id>` directory.
  It may replace only its own previously staged developer build. It must not
  overwrite arbitrary user-installed native plugins.
- **Baseline:** Launch the original world/mod selection using the actual
  `v3nl.launcher.launch_game()` codepath with native plugins disabled.
- **Candidate:** Launch the same game, mod order, flags and start with the
  candidate enabled via the same launcher. Never run a manual injector,
  standalone Frida injector, separate subprocess game launcher or modified EXE.
- **Observe:** Use the isolated launcher-managed profiles, saved manifests,
  game timers and native counters. Record crash/init errors and missing days.
  Treat measurements taken under different load as inconclusive.
- **Accept:** Require matched elapsed-time improvement and game-state parity.
  Queue polling, sample counts and task-time savings alone do not prove a fix.

The executable build always uses exactly the same game version in both arms.
If the installed game updates, rebuild/revalidate the plugin; don't silently
reuse the prior native addresses. The original 1,639-country 1337 scenario
remains intact. No country-reduction shortcuts, skipped AI or simulation-fidelity
changes unless specifically authorized for a separate experimental variant.

## Use

From the V3NL repository:

`python run.py --native-experiment .\path\to\experiment.json --dry-run`

This prints plans without creating managed profiles, building a DLL or
starting the game.

Once the current conversation explicitly authorizes a run:

`python run.py --native-experiment .\path\to\experiment.json --execute`

The runner builds the DLL in the supplied source directory (if a build block
is present), computes and pins its hash, validates the plugin, stages it,
runs baseline then candidate sequentially, waits for each bounded game
process, collects full-day timer rows, and writes its receipts under
`%LOCALAPPDATA%\Victoria3NativeLoader\experiments`.

Do not use `--execute` in scheduled unattended tests without a separate
explicit owner authorization. Do not touch other game processes; the current
runner refuses to start if any Victoria 3 process already exists. Sharing
the shader cache may prevent redundant shader compilation; save directories
are not shared by experiment profiles.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Must equal 1 |
| `id` | Stable experiment identifier, 3–41 lower-case chars |
| `game_exe` | Exact installed `victoria3.exe` |
| `base_userdir` | Existing Paradox Victoria 3 user data |
| `mods` | Ordered list of existing mod directories |
| `candidate_plugin_id` | Developer DLL plugin ID |
| `game_arguments` | Fixed, bounded native game arguments including `-run_until` |
| `build` | Compiler command array, cwd, DLL output path, manifest template |
| `repetitions` | 1–5 matched baseline/candidate pairs |
| `timeout_seconds` | Per-arm timeout, default 900 |
| `min_complete_days` | Minimum accepted complete game days, default 1 |

A build manifest template lists `supported_game_sha256`; the DLL SHA
is computed automatically *after* the compiler produces the artifact.
An existing staged plugin may be tested without a `build` block.

## Current limits

- This is a **live-game-tested developer experiment interface**, not a claim
  that any performance optimization plugin is ready.
- On 2026-11-24 the V3NL experiment runner built/loaded the `tu-loader-smoke`
  no-op DLL and completed two GUI Terra Universalis Alpha 1337 29-day trials
  with normal exits and no injection errors. That proves loader integration,
  **not** native scheduler-detour safety, game-state parity or optimization.
- Game-state parity testing is a separate required acceptance gate.
- No runtime hook installation may use Windows SuspendThread or ResumeThread.
- A plugin must not be enabled without explicit user selection or an
  explicitly authorized experimental manifest.
