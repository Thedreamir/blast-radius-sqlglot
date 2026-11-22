#!/bin/bash
# usage: fprun.sh NUMBER TEST_ID   (run from a sqlglot checkout at eb11aec, FP_DIR = output dir)
n=$1; id=$2; [ -f "$FP_DIR/$n.json" ] && exit 0
export SKIP_INTEGRATION=0 PYTHONPATH=$PWD:$(dirname "$0")
FP_OUT=$FP_DIR/$n.json timeout 200 python -m pytest -q --no-header -p no:cacheprovider -p fp_plugin "$id" >/dev/null 2>&1
