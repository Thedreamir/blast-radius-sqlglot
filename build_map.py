"""Builds map.json from the pinned sqlglot checkout: per-line test coverage,
statement/function spans, fixture readers, dialect name -> tests, names bound at import time.
Usage: build_map.py SQLGLOT_DIR COVERAGE_DATA FIXTURE_TRACE_DIR TESTS_JSON OUT"""
import ast, bisect, glob, json, os, re, sys, tokenize, io
import coverage

SG, COV, FXD, TJ, OUT = sys.argv[1:6]
CHILD = json.load(open(sys.argv[6]))
tests = json.load(open(TJ))["tests"]
ids = [t["id"] for t in tests]
idx = {t: i for i, t in enumerate(ids)}
ctx2idx = {}
for t, i in idx.items():
    f, c, fn = (t.split("::") + [None])[:3] if t.count("::") == 2 else (t.split("::")[0], None, t.split("::")[-1])
    pass
ctx2idxs = {}
for t, i in idx.items():
    parts = t.split("::")
    cls = "::".join(parts[:2]) if len(parts) == 3 else None
    for ph in ("run", "setup", "teardown"):
        ctx2idxs[t + "|" + ph] = [i]
    if cls:
        ctx2idxs[t + "|setup"] = [idx[x] for x in ids if x.startswith(cls + "::")]

cd = coverage.CoverageData(COV); cd.read()
print('contexts', len(cd.measured_contexts()))
sets, setidx = [], {}
def sid(s):
    k = tuple(sorted(s))
    if k not in setidx:
        setidx[k] = len(sets); sets.append(list(k))
    return setidx[k]

# test sources
test_src = {}  # idx -> lowercase text
for f in sorted(set(t["file"] for t in tests)):
    src = open(os.path.join(SG, f), encoding="utf-8").read()
    tree = ast.parse(src)
    segs = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    segs[(node.name, fn.name)] = ast.get_source_segment(src, fn) or ""
        elif isinstance(node, ast.FunctionDef):
            segs.setdefault((None, node.name), ast.get_source_segment(src, node) or "")
    for t in tests:
        if t["file"] != f: continue
        parts = t["id"].split("::")
        key = (parts[1], parts[2]) if len(parts) == 3 else (None, parts[1])
        test_src[idx[t["id"]]] = (segs.get(key, "") + " " + os.path.basename(f)).lower()

out = {"ids": ids, "files": {}, "fx": {}, "dial": {}, "names": {}, "tfile": {}}
for t in tests:
    out["tfile"].setdefault(t["file"], []).append(idx[t["id"]])

class Info(ast.NodeVisitor): pass

names_tests = {}  # token -> set(test idx)  (filled later)
import_tokens = {}  # token -> list of (file, start, end) lines mentioning

srcfiles = sorted(glob.glob(os.path.join(SG, "sqlglot", "**", "*.py"), recursive=True))
filelines = {}
for path in srcfiles:
    rel = os.path.relpath(path, SG)
    src = open(path, encoding="utf-8").read()
    lines = src.split("\n")
    filelines[rel] = lines
    n = len(lines)
    tree = ast.parse(src)
    unit = [None] * (n + 2); funcr = [None] * (n + 2); instr = [False] * (n + 2); imp = [True] * (n + 2)
    cands = []  # (size, start, end)
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            end = getattr(node, "end_lineno", node.lineno)
            if hasattr(node, "body") and isinstance(getattr(node, "body"), list) and node.body:
                s = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
                hdr_end = node.body[0].lineno - 1
                # header may include multiline signature; docstring etc belongs to body
                cands.append((hdr_end - s, s, max(hdr_end, node.lineno)))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs.append((s, end))
            else:
                cands.append((end - node.lineno, node.lineno, end))
        if isinstance(node, ast.Lambda):
            cands.append((node.end_lineno - node.lineno, node.lineno, node.end_lineno))
            funcs.append((node.lineno, node.end_lineno))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.end_lineno > node.lineno:
            for l in range(node.lineno, node.end_lineno + 1): instr[l] = True
        if isinstance(node, ast.JoinedStr) and node.end_lineno > node.lineno:
            for l in range(node.lineno, node.end_lineno + 1): instr[l] = True
    for size, s, e in sorted(cands, key=lambda c: -c[0]):
        for l in range(s, e + 1): unit[l] = (s, e)
    for s, e in sorted(funcs, key=lambda c: -(c[1] - c[0])):
        for l in range(s, e + 1):
            funcr[l] = (s, e); imp[l] = False
    # the def header of a function executes at import time; body lines are not import time
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            hdr_end = node.body[0].lineno - 1
            s = min([node.lineno] + [d.lineno for d in node.decorator_list])
            for l in range(s, max(hdr_end, node.lineno) + 1): imp[l] = True; funcr[l] = None if l <= max(hdr_end, node.lineno) and False else funcr[l]
    # coverage
    ctxmap = cd.contexts_by_lineno(path) if path in cd.measured_files() else {}
    lcov = {}
    thr = []
    extra = {}
    for tid, fm in CHILD.items():
        for ln in fm.get(path, []):
            extra.setdefault(ln, set()).add(idx[tid])
    for ln in set(ctxmap) | set(extra):
        ts = set(j for c in ctxmap.get(ln, ()) for j in ctx2idxs.get(c, ())) | extra.get(ln, set())
        if ts: lcov[ln] = sid(ts)
    # import-time bound names
    for node in ast.walk(tree):
        pass
    toks = set()
    for node in tree.body:
        pass
    def collect(body):
        for node in body:
            if isinstance(node, ast.ClassDef):
                toks.add(node.name); collect(node.body)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                toks.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                tg = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in tg:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name): toks.add(x.id)
                for x in ast.walk(node):
                    if isinstance(x, ast.Dict):
                        for k in x.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str): toks.add(k.value)
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For)):
                collect(node.body)
    collect(tree.body)
    out["files"][rel] = {
        "n": n,
        "unit": {str(l): list(unit[l]) for l in range(1, n + 1) if unit[l]},
        "func": {str(l): list(funcr[l]) for l in range(1, n + 1) if funcr[l] and not imp[l]},
        "instr": [l for l in range(1, n + 1) if instr[l]],
        "imp": [l for l in range(1, n + 1) if imp[l]],
        "cov": {str(k): v for k, v in lcov.items()},
        "thr": thr,
        "ic": [ln for ln, cs in ctxmap.items() if "" in cs],
    }
    for t in toks: import_tokens.setdefault(t, set()).add(rel)
# names -> tests: tests covering lines (anywhere in sqlglot, any file) that mention token, plus tests whose source mentions it
allsrc = {rel: ls for rel, ls in filelines.items()}
wordre = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
widx = {}  # word -> set of test idx covering lines containing it
for rel, ls in allsrc.items():
    cov = out["files"][rel]["cov"]
    for i, line in enumerate(ls, 1):
        v = cov.get(str(i))
        if v is None: continue
        for w in set(wordre.findall(line)):
            widx.setdefault(w, set()).update(sets[v])
wordlist = sorted(widx)
bigtext = "\n".join(wordlist)
lowsrc = list(test_src.items())
for tok, files in import_tokens.items():
    if len(tok) < 3 or tok in ("self", "cls", "exp"): continue
    ts = set()
    if wordre.fullmatch(tok):
        if len(tok) >= 6:
            for m in re.finditer(r"^[^\n]*" + re.escape(tok) + r"[^\n]*$", bigtext, re.M):
                ts |= widx[m.group(0)]
        else:
            ts |= widx.get(tok, set())
    else:
        for rel, ls in allsrc.items():
            cov = out["files"][rel]["cov"]
            for i, line in enumerate(ls, 1):
                if str(i) in cov and tok in line: ts.update(sets[cov[str(i)]])
    low = tok.lower()
    if len(tok) >= 4:
        for ti, s in lowsrc:
            if low in s: ts.add(ti)
    out["names"][tok] = sid(ts)
# dialect names
dnames = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(SG, "sqlglot", "dialects", "*.py")))
for d in dnames:
    ts = set(out["tfile"].get(f"tests/dialects/test_{d}.py", []))
    pat = re.compile(r"(?<![a-z0-9_])" + re.escape(d) + r"(?![a-z0-9_])")
    for ti, s in test_src.items():
        if pat.search(s): ts.add(ti)
    for sub in ("dialects", "parsers", "generators", "typing"):
        rel = f"sqlglot/{sub}/{d}.py"
        if rel in out["files"]:
            for v in out["files"][rel]["cov"].values(): ts.update(sets[v])
    out["dial"][d] = ts
# subclasses: a dialect's attributes are inherited by dialects built on it
cls2file, bases = {}, {}
for d in dnames:
    p = os.path.join(SG, "sqlglot", "dialects", d + ".py")
    tree = ast.parse(open(p, encoding="utf-8").read())
    for n in tree.body:
        if isinstance(n, ast.ClassDef):
            cls2file[n.name] = d
            bases[n.name] = [b.id for b in n.bases if isinstance(b, ast.Name)] + [b.attr for b in n.bases if isinstance(b, ast.Attribute)]
changed = True
while changed:
    changed = False
    for c, bs in bases.items():
        for b in bs:
            if b in cls2file and cls2file[b] != cls2file[c]:
                before = len(out["dial"][cls2file[b]])
                out["dial"][cls2file[b]] |= out["dial"][cls2file[c]]
                if len(out["dial"][cls2file[b]]) != before: changed = True
for d in dnames: out["dial"][d] = sid(out["dial"][d])
# fixtures
fx = {}
for f in glob.glob(os.path.join(FXD, "*.json")):
    for k, v in json.load(open(f)).items():
        fx.setdefault(k, set()).update(v)
fxmap = {}
for tid, files in fx.items():
    if tid not in idx: continue
    for fl in files:
        fxmap.setdefault(fl, set()).add(idx[tid])
for fl, ts in fxmap.items():
    if any(ids[i].startswith("tests/test_executor.py") for i in ts):
        ts = ts | set(out["tfile"]["tests/test_executor.py"])
    if any(ids[i].startswith("tests/test_optimizer.py") and "tpc" in fl for i in ts):
        ts = ts | set(out["tfile"]["tests/test_executor.py"])
    out["fx"][fl] = sid(ts)
out["fx_all"] = sorted(os.path.relpath(os.path.join(d, f), SG) for d, _, fs in os.walk(os.path.join(SG, "tests", "fixtures")) for f in fs)
poolre = re.compile(r"check_file|pool|parse_and_optimize|thread|mp_execute")
pool = [ti for ti, s in test_src.items() if poolre.search(s)]
out["pool"] = pool
out["sub"] = [ti for ti, s in test_src.items() if "subprocess" in s]
out["pool_opt"] = [ti for ti in pool if re.search(r"optimize|optimizer\.optimize", test_src[ti])]
out["pool_mod"] = {}
for rel in out["files"]:
    b = os.path.basename(rel)[:-3]
    if "/optimizer/" in rel:
        out["pool_mod"][rel] = sid(set(ti for ti in pool if b.lower() in test_src[ti]) | set(out["pool_opt"]) | set(ti for ti in pool if ids[ti].startswith("tests/test_executor.py")))
out["sets"] = sets
json.dump(out, open(OUT, "w"), separators=(",", ":"))
print("files", len(out["files"]), "sets", len(sets), "names", len(out["names"]), "size", os.path.getsize(OUT))
