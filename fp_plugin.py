import sys, os, json
def pytest_sessionfinish(session, exitstatus):
    mods = sorted(m for m in sys.modules if m == "sqlglot" or m.startswith("sqlglot."))
    with open(os.environ["FP_OUT"], "w") as f: json.dump([exitstatus, mods], f)
