# Native performance hook starter

This is a no-op native DLL template, not a performance optimization.

For each new hook, copy this folder to its own plugin project, give the
plugin a unique ID, implement the hook against verified current-game
signatures, and preserve the exported `V3NL_PluginInit` interface.

Run `build.cmd` through the V3NL experiment manifest's `build.command`.
The launcher then validates, stages, and selects the newly built DLL.

See [the experiment contract](../../docs/PERFORMANCE_TEST_CONTRACT.md).
Never create a separate injector, and never suspend or resume game threads.
