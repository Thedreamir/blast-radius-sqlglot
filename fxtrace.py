import builtins, io, os, json, atexit
_open = builtins.open
rec = {}
def cur():
    return os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0] or "<collect>"
def op(f, *a, **k):
    try:
        if isinstance(f, (str, bytes, os.PathLike)):
            p = os.fspath(f)
            if isinstance(p, bytes): p = p.decode()
            if "tests/" in p and "fixtures" in p or p.endswith((".sql", ".json", ".txt", ".yaml")) and "/tests/" in p:
                rec.setdefault(cur(), set()).add(os.path.relpath(p))
    except Exception: pass
    return _open(f, *a, **k)
builtins.open = op; io.open = op
def dump():
    with _open(os.environ.get("FXOUT","/tmp/br/fx.json"), "w") as fh:
        json.dump({k: sorted(v) for k, v in rec.items()}, fh)
atexit.register(dump)
