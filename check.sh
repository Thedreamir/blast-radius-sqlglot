#!/bin/bash
# Self-check on the sample kit: runs the selector and the track's scorer, fails on any miss or if the total
# goes above the budget (default 215 s).  Usage: ./check.sh SAMPLE_DIR SCORER_PY [BUDGET_SECONDS]
set -e
D=$1; S=$2; B=${3:-215}
BR_DATA=$D python selector.py > /tmp/check_out.jsonl
python "$S" "$D" "$D/answers.json" /tmp/check_out.jsonl | tee /tmp/check_score.txt
grep -q "^Misses:    0 " /tmp/check_score.txt
python - "$B" <<'PY'
import re, sys
t = float(re.search(r"Simulated: ([0-9.]+) s", open("/tmp/check_score.txt").read()).group(1))
assert t <= float(sys.argv[1]), f"over budget: {t}"
print("ok", t)
PY
