# Developer guide: native performance experiments

Native engine-performance hooks are developed **as standalone V3NL DLL plugins
from their first build**. Every runtime A/B test must compile and validate the
candidate, then launch both the unmodified baseline and the plugin-enabled
candidate through this launcher's own `launch_game()` path. There is no
separate manual injector in the supported workflow.

```powershell
# Static plan: does not compile, launch a game, or inject a DLL
python run.py --native-experiment path\to\experiment.json --dry-run

# Only after explicitly authorizing the game test:
python run.py --native-experiment path\to\experiment.json --execute
```

The developer pipeline validates build outputs, pins the game executable and
DLL hashes, stages only developer-owned plugin directories, and runs isolated,
bounded baseline/candidate trials. It refuses to start while any other
Victoria 3 process is running. It preserves existing mod paths and optionally
shares the shader cache while isolating saves. No native optimization has yet
been proven, and this new pipeline has not been tested end-to-end in game.

See [Performance Test Contract](PERFORMANCE_TEST_CONTRACT.md),
[example experiment manifest](performance_experiment.example.json),
and [AGENTS.md](../AGENTS.md). Runtime testing is never automatic merely because
a manifest exists; explicit authorization remains necessary.
