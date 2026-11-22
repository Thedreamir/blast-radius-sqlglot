# Blast Radius selector

Picks which sqlglot tests a patch can break, then splits them over up to 8 workers.

How it works:

1. `map.json` is built once from sqlglot at the pinned commit `eb11aec`. It holds, for every source line, which tests executed it (per-test coverage, including code that runs in spawned worker processes), which tests read each fixture file, and which tests mention each dialect or import-time name. It is plain data, not a table of patches.
2. `selector.py` reads each patch, finds the statements it changes, and selects the tests that ran those statements. Comment-only edits outside string literals select nothing. Changes to class or module level code (which run at import) select the tests tied to the dialect or name. Anything it does not understand runs the full suite.
3. The selection is packed with longest-first onto the worker count that minimises busiest worker plus 2 s per worker.

Rebuild the map: `collect_coverage.sh` (per-test coverage), `fxtrace.py` (fixture reads), `mkchild.py` (spawned process coverage), then `build_map.py`.

MIT licensed.
