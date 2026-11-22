#!/bin/bash
cd /tmp/br/sqlglot; export SKIP_INTEGRATION=0 PYTHONPATH=$PWD
start=$(date +%s); touch /tmp/br/done2.txt
for f in $(cat /tmp/br/all.txt); do
  grep -qx "$f" /tmp/br/done2.txt && continue
  [ $(( $(date +%s) - start )) -gt 75 ] && break
  COVERAGE_FILE=/tmp/br/cov2.data.$(echo $f | tr / _) ../v/bin/python -m pytest -q --no-header -p no:cacheprovider --timeout=300 --cov=sqlglot --cov-context=test --cov-config=/tmp/br/cov2.rc --cov-report= $f 2>&1 | tail -1 | cut -c1-60
  echo $f >> /tmp/br/done2.txt
done
echo done $(wc -l < /tmp/br/done2.txt)
