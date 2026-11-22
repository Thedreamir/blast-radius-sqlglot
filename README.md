# blast-radius

A test suite is a set of questions. A patch changes the answer to a few of them and is irrelevant to the rest. Running all of them to find out which is the slow way to ask.

The minimal sufficient set for a patch is the tests that execute the code the patch changes. Nothing else can notice it.

**30 sample commits: 183.6 s total, 0 missed failures.** Running the full suite on the same set takes about 1200 s. The selector itself costs about 2.3 s for the whole batch.

## The idea

File-path and name matching guess at relevance: "this edit is in `generators/clickhouse.py`, run `test_clickhouse.py`". Sqlglot breaks that guess, because a change in shared code fails tests in other dialects and in the optimizer. Measured on the 30 samples with the obvious name map (`dialects|generators|parsers|typing/X.py` to `test_X.py`, `optimizer/*` and its fixtures to `test_optimizer.py`, `foo.py` to `test_foo.py`): it misses at least one failing test on 5 of the 18 commits that have failures, and 42 of the 73 failing tests overall.

This does not guess. It records what each test actually ran, once, then asks the same question of every patch: which tests ran the lines you touched?

## How it works

1. **Coverage map.** `map.json` is built from sqlglot at the pinned commit `eb11aec`. For every source line it stores which tests executed it, including code run in spawned worker processes. It also stores which tests read which fixture files, and which tests touch each dialect or import-time name. It is a map of the code, not a table of patches.
2. **Patch analysis.** `selector.py` reads the diff, finds the statements that changed, and selects the tests that ran them. A comment-only edit selects nothing. Class and module level code runs at import, so a change there selects by dialect and name instead of by line. A plain literal edit in a class body (a constant, a flag) selects only the tests that build that class and its subclasses.
3. **Import check.** The image keeps sqlglot's source at the pinned commit. The selector applies the patch to a copy and checks it still compiles and, for import-time edits, still imports. If it does not, every test that imports that module is added (measured per test, in a fresh interpreter, stored in `map.json`). If the core fails, everything runs.
4. **Safe fallback.** Anything it does not understand runs the full suite. A slow answer beats a wrong one.
5. **Packing.** Selected tests are split over up to 8 workers, longest first, at the worker count that minimises the busiest worker plus 2 s per worker.

One slow test, `test_execute_tpcds` (about 21.5 s), is kept on purpose. Dropping it would save time on most patches and cost a miss on some.

## Testing

Beyond the samples, the selector was checked against mutants: lines changed in sqlglot, the real suite run on each, and the result compared with the selection. 0 misses, including 18 class-attribute mutants. One import-time bug turned up this way and is fixed.

## Rebuild the map

Against a checkout of sqlglot at `eb11aec`:

1. `collect_coverage.sh` for per-test coverage
2. `fxtrace.py` for fixture reads
3. `mkchild.py` for coverage of spawned processes
4. `build_map.py` to merge it all into `map.json`
5. `fprun.sh` per test, then `build_fp.py`, for the import footprints
6. `build_creators.py` for which tests build each expression class

The scripts keep the paths of the original build. Edit them for your machine.

## Check

`./check.sh SAMPLE_DIR SCORER_PY` runs the selector on a sample kit, scores it, and fails on any miss or if the total goes over budget.

## License

MIT. See `LICENSE`.
