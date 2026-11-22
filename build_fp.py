"""Adds per-module import footprints to map.json.
Usage: build_fp.py MAP_JSON TESTS_JSON FOOTPRINT_DIR
FOOTPRINT_DIR holds one N.json per test number: [exit_status, [sqlglot modules loaded when
that test ran alone in a fresh interpreter]]. Written by fp_plugin.py via fprun.sh."""
import json, sys
from collections import defaultdict
mp, tj, fd = sys.argv[1:4]
M = json.load(open(mp))
tests = json.load(open(tj))["tests"]
n = len(M["ids"])
num2idx = {t["number"]: i for i, t in enumerate(tests)}
assert [t["id"] for t in tests] == M["ids"]
mods = defaultdict(set)
for t in tests:
    _, loaded = json.load(open(f"{fd}/{t['number']}.json"))
    for m in loaded:
        mods[m].add(num2idx[t["number"]])
fp = {}
for m, s in mods.items():
    rel = m.replace(".", "/")
    # package vs module: both the module file and package __init__ may exist
    for r in (rel + ".py", rel + "/__init__.py"):
        key = r
        if len(s) > n // 2:
            fp[key] = {"not": sorted(set(range(n)) - s)}
        else:
            fp[key] = {"in": sorted(s)}
M["fp"] = fp
json.dump(M, open(mp, "w"), separators=(",", ":"))
print("fp modules", len(fp))
