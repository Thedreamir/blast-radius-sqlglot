"""Blast Radius selector: picks the tests a patch can break from a coverage map
built on the pinned sqlglot commit (see build_map.py), then packs them onto workers."""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

DATA = Path(os.environ.get("BR_DATA", "/data"))
HERE = Path(__file__).resolve().parent
KW = set("self cls exp None True False and or not if else elif return for in is def class import from lambda while try except with as pass raise yield isinstance len str int list dict set tuple".split())

M = json.load((HERE / "map.json").open())
FILES, SETS, NAMES, DIAL, FX = M["files"], M["sets"], M["names"], M["dial"], M["fx"]
ALL = None
SG = Path(os.environ.get("BR_SQLGLOT", "/opt/sg"))   # sqlglot source at the pinned commit (see Dockerfile)


def sset(i):
    return set(SETS[i])


def parse_patch(text):
    """-> {path: [hunk]} hunk = dict(old_start, removed=[(oldno,text)], added=[text], anchor)"""
    files, cur, hunk = {}, None, None
    old = 0
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            cur = {"old": m.group(1), "new": m.group(2), "hunks": [], "binary": False, "special": False}
            files[m.group(1)] = cur
            hunk = None
        elif cur is None:
            continue
        elif line.startswith(("rename from", "rename to", "new file mode", "deleted file mode", "old mode", "new mode", "similarity")):
            cur["special"] = True
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            cur["binary"] = True
        elif line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            old = int(m.group(1))
            hunk = {"removed": [], "added": [], "anchor": None, "blocks": []}
            cur["hunks"].append(hunk)
            blk = None
        elif hunk is not None:
            if line.startswith("-") and not line.startswith("---"):
                if blk is None or blk["done"]:
                    blk = {"removed": [], "added": [], "anchor": old - 1, "done": False}
                    hunk["blocks"].append(blk)
                blk["removed"].append((old, line[1:])); old += 1
            elif line.startswith("+") and not line.startswith("+++"):
                if blk is None or blk["done"]:
                    blk = {"removed": [], "added": [], "anchor": old - 1, "done": False}
                    hunk["blocks"].append(blk)
                blk["added"].append(line[1:])
            elif line.startswith(" ") or line == "":
                if blk is not None: blk["done"] = True
                old += 1
            elif line.startswith("\\"):
                pass
    return files


def strip_comment_lines(lines):
    return [l for l in lines if l.strip() and not l.strip().startswith("#")]


def ind(s):
    return len(s) - len(s.lstrip())


def tests_for_range(fi, s, e, path=None):
    cov = fi["cov"]
    out = set()
    thr = False
    for l in range(s, e + 1):
        v = cov.get(str(l))
        if v is not None: out.update(SETS[v])
    # lines run in worker threads carry no test context: add the tests that use the pool
    return out


def toks_of(line):
    t = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", line))
    t |= set(re.findall(r"\"([A-Za-z_][A-Za-z0-9_]*)\"", line))
    t |= set(re.findall(r"'([A-Za-z_][A-Za-z0-9_]*)'", line))
    return {x for x in t if x not in KW and len(x) >= 3}


def dialect_of(path):
    m = re.match(r"sqlglot/(?:dialects|parsers|generators|typing)/([a-z0-9_]+)\.py$", path)
    if m and m.group(1) in DIAL and m.group(1) not in ("dialect", "__init__"):
        return m.group(1)
    return None


def full():
    global ALL
    if ALL is None:
        ALL = set(range(len(M["ids"])))
    return ALL


GATE = set()   # files whose patch touched import-time lines


def select_source(path, hunks):
    fi = FILES.get(path)
    if fi is None:
        return None  # unknown source file: full suite
    unit, func, imp, instr = fi["unit"], fi["func"], set(fi["imp"]), set(fi["instr"])
    imp |= set(fi["ic"])  # lines that also ran while sqlglot was being imported
    sel = set()
    for h in hunks:
        for b in h["blocks"]:
            rem, add = b["removed"], b["added"]
            add_code = strip_comment_lines(add)
            rem_code = strip_comment_lines([t for _, t in rem])
            # pure comment/blank insertion or removal, not touching a string literal
            if not rem_code and not add_code:
                if rem:
                    inside = any(n in instr for n, _ in rem)
                else:
                    inside = b["anchor"] in instr and (b["anchor"] + 1) in instr
                if not inside:
                    continue
            if rem and len(rem) == len(add) and all(ind(a) == ind(r) for (_, r), a in zip(rem, add)) and \
               not any(n in instr for n, _ in rem):
                # in-place edit: tests that run the replaced statements
                for n, _ in rem:
                    u = unit.get(str(n))
                    if u is None:
                        return None
                    if n in imp:
                        GATE.add(path)
                        r = import_time(path, fi, n, rem, add, u)
                        if r is None: return None
                        sel |= r
                    else:
                        sel |= tests_for_range(fi, u[0], u[1], path)
                continue
            # structural change: whole enclosing function(s)
            probe = [n for n, _ in rem] or [b["anchor"], b["anchor"] + 1]
            for n in probe:
                f = func.get(str(n))
                if f is not None and n not in imp:
                    sel |= tests_for_range(fi, f[0], f[1], path)
                else:
                    GATE.add(path)
                    r = import_time(path, fi, n, rem, add, unit.get(str(n)))
                    if r is None: return None
                    sel |= r
    return sel


LIT = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b0[xX][0-9a-fA-F_]+\b|\b\d[\d_]*(?:\.\d+)?\b|\bTrue\b|\bFalse\b|\bNone\b)""")


def literal_only(rem, add):
    """True when the block differs only in literal values (numbers, strings, True/False/None)."""
    if len(rem) != len(add):
        return False
    mask = lambda t: LIT.sub("0", t)
    return all(mask(r) == mask(a) for (_, r), a in zip(rem, add))


def ancestors(name, graph):
    out, todo = set(), list(graph.get(name, []))
    while todo:
        b = todo.pop()
        if b not in out:
            out.add(b); todo.extend(graph.get(b, []))
    return out


def class_attr(path, n, base):
    """A literal change to an attribute in the body of a plain expression class only matters to code that builds
    an instance of that class or of a subclass (see build_creators.py). Function classes are built from SQL text by
    name, and classes read at import time keep the broad path."""
    spans = M.get("clsline", {}).get(path)
    cr = M.get("creators")
    if not spans or not cr:
        return None
    graph = M["cls"]
    for start, end, name, body in spans:
        if any(a <= n <= b for a, b in body):
            fam = {name} | {c for c in graph if name in ancestors(c, graph)}
            sel = set(base)
            for c in fam:
                v = cr.get(c)
                if v is None or v["imp"]:
                    return None
                sel |= set(v["tests"])
            return sel
    return None


def import_time(path, fi, n, rem, add, u):
    """Change to module/class level code: it runs at import, so find who depends on it."""
    sel = set(M["sub"])
    if u is not None:
        sel |= tests_for_range(fi, u[0], u[1], path)
    toks = set()
    for _, t in rem: toks |= toks_of(t)
    for t in add: toks |= toks_of(t)
    d = dialect_of(path)
    if d is not None:
        hits = set()
        for t in toks:
            if t in NAMES: hits |= sset(NAMES[t])
        sel |= sset(DIAL[d])
        return sel
    # shared code (generator, parser, expressions, optimizer, ...): other modules may read the changed name while
    # they are being built, which no per-test coverage can show. Only a pure literal swap is analysed; any other
    # class or module level edit runs the full suite.
    if not literal_only(rem, add):
        return None
    r = class_attr(path, n, set(M["sub"]))
    if r is not None:
        return r
    hit = False
    for t in toks:
        if t in NAMES:
            sel |= sset(NAMES[t]); hit = True
    if not hit:
        return None
    return sel


def select_fixture(path):
    v = FX.get(path)
    if v is None:
        return None
    return sset(v)


def apply_hunks(orig, raw_hunks):
    """Apply unified-diff hunks (old_start, lines with ' ', '-', '+' prefixes) to text; None if they do not fit."""
    lines = orig.split("\n")
    out, pos = [], 0
    for old_start, hl in raw_hunks:
        start = old_start - 1 if any(not l.startswith("+") for l in hl) else old_start
        if start < pos or start > len(lines):
            return None
        out.extend(lines[pos:start]); pos = start
        for l in hl:
            if l.startswith("+"):
                out.append(l[1:])
            else:
                if pos >= len(lines) or lines[pos] != l[1:]:
                    return None
                if l.startswith(" "):
                    out.append(lines[pos])
                pos += 1
    out.extend(lines[pos:])
    return "\n".join(out)


def raw_hunks(patch_text):
    res, cur, hunks, ok = {}, None, None, True
    ls = patch_text.split("\n")
    if ls and ls[-1] == "":
        ls.pop()
    for line in ls:
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", line)
            cur = m.group(1); hunks = res.setdefault(cur, []); h = None
        elif cur is None:
            continue
        elif line.startswith("@@"):
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            h = (int(m.group(1)), []); hunks.append(h)
        elif line.startswith(("---", "+++")) and h is None:
            continue
        elif h is not None and line[:1] in ("+", "-", " "):
            h[1].append(line)
        elif h is not None and line == "":
            h[1].append(" ")
    return res


def conservative(path):
    """Tests that would fail if this module could not be imported."""
    v = M.get("fp", {}).get(path)
    if v is None:
        return None
    if "in" in v:
        return set(v["in"])
    return full() - set(v["not"])


def import_gate(patch_text, changed):
    """Apply the patch to a copy of sqlglot and check it still imports. Returns the tests that fail when it does not,
    or None (-> full suite) when this cannot be judged."""
    raw = raw_hunks(patch_text)
    patched = {}
    for p in changed:
        try:
            orig = (SG / p).read_text(encoding="utf-8")
        except OSError:
            return None
        new = apply_hunks(orig, raw.get(p, []))
        if new is None:
            return None
        patched[p] = new
    bad = set()
    deep = [p for p in changed if p in GATE]
    for p, text in patched.items():
        try:
            compile(text, p, "exec")
        except (SyntaxError, ValueError):
            c = conservative(p)
            if c is None: return None
            bad |= c
    if bad:
        return bad
    if not deep:
        return bad
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "sqlglot"
        root.mkdir()
        prefix = "sqlglot/"
        def mirror(src, dst, rel):
            dst.mkdir(exist_ok=True)
            for e in os.scandir(src):
                r = rel + e.name
                if e.name == "__pycache__":
                    continue
                if e.is_dir():
                    if any(c.startswith(r + "/") for c in patched):
                        mirror(e.path, dst / e.name, r + "/")
                    else:
                        os.symlink(e.path, dst / e.name)
                elif r in patched:
                    (dst / e.name).write_text(patched[r], encoding="utf-8")
                else:
                    os.symlink(e.path, dst / e.name)
        mirror(str(SG / "sqlglot"), root, "sqlglot/")
        # A class or module body edit can break the import of modules that build on it while the edited module
        # itself still imports, so every module of the package is imported, not only the touched ones.
        mods = []
        for dp, dn, fn in os.walk(SG / "sqlglot"):
            dn[:] = sorted(d for d in dn if d != "__pycache__")
            for f in sorted(fn):
                if f.endswith(".py") and f != "__main__.py":
                    rel = os.path.relpath(os.path.join(dp, f), SG)[:-3].replace(os.sep, ".")
                    mods.append(rel[:-9] if rel.endswith(".__init__") else rel)
        code = ("import importlib,sys\n"
                "bad=[]\n"
                "try:\n import sqlglot\n"
                "except BaseException:\n print('CORE'); sys.exit(0)\n"
                "for m in sys.argv[1:]:\n"
                " try: importlib.import_module(m)\n"
                " except BaseException: bad.append(m)\n"
                "print(' '.join(bad))\n")
        env = dict(os.environ, PYTHONPATH=td, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-c", code] + mods, capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            print('gate error', r.stderr[-400:], file=sys.stderr)
            return None
        out = r.stdout.strip()
        if out == "CORE":
            return full()
        for m in out.split():
            c = conservative(m.replace(".", "/") + ".py") or conservative(m.replace(".", "/") + "/__init__.py")
            if c is None: return None
            bad |= c
    return bad


def select_commit(patch_text):
    files = parse_patch(patch_text)
    if not files:
        return full()
    GATE.clear()
    sel = set()
    changed = []
    for p, info in files.items():
        if info["binary"] or info["special"] or info["old"] != info["new"]:
            return full()
        if p.startswith("sqlglot/") and p.endswith(".py"):
            changed.append(p)
            r = select_source(p, info["hunks"])
        elif p.startswith("tests/fixtures/"):
            r = select_fixture(p)
            if r is None and p in M["fx_all"]:
                r = set()   # fixture nobody opened
        elif p.startswith("tests/") and p.endswith(".py") and p in M["tfile"]:
            r = set(M["tfile"][p])
        else:
            r = None
        if r is None:
            return full()
        sel |= r
    if changed and sel is not None:
        g = import_gate(patch_text, changed)
        if g is None:
            return full()
        sel |= g
    return sel


def pack(sel, secs):
    """Pick worker count k<=8 minimising max load + 2s*k, LPT assignment."""
    if not sel:
        return []
    items = sorted(sel, key=lambda i: -secs[i])
    best = None
    for k in range(1, 9):
        loads = [0] * k
        ws = [[] for _ in range(k)]
        for i in items:
            j = loads.index(min(loads))
            ws[j].append(i); loads[j] += secs[i]
        cost = max(loads) + 2000 * k
        if best is None or cost < best[0]:
            best = (cost, [w for w in ws if w])
    return best[1]


def main():
    tj = json.loads((DATA / "tests.json").read_text())["tests"]
    num = {t["id"]: t["number"] for t in tj}
    secs_by_num = {t["number"]: round(t["seconds"] * 1000) for t in tj}
    # map index (reference ids) -> number in this run's tests.json
    idx2num = [num.get(i) for i in M["ids"]]
    secs = [secs_by_num.get(n, 0) if n is not None else 0 for n in idx2num]
    unknown = [n for n in num.values() if n not in set(x for x in idx2num if x is not None)]
    for p in sorted((DATA / "commits").glob("*.patch")):
        try:
            sel = select_commit(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            print("error", p.stem, repr(e), file=sys.stderr)
            sel = full()
        if sel and len(sel) == len(M["ids"]):
            sel = set(range(len(M["ids"])))
        ws = pack(sel, secs)
        out = [[idx2num[i] for i in w if idx2num[i] is not None] for w in ws]
        if sel and unknown:
            if out:
                out[0] = out[0] + unknown  # tests this map never saw: always run them
            else:
                out = [unknown]
        print(json.dumps({"commit": p.stem, "workers": [w for w in out if w]}))


if __name__ == "__main__":
    main()
