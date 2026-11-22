"""Blast Radius selector: picks the tests a patch can break from a coverage map
built on the pinned sqlglot commit (see build_map.py), then packs them onto workers."""
import json, os, re, sys
from pathlib import Path

DATA = Path(os.environ.get("BR_DATA", "/data"))
HERE = Path(__file__).resolve().parent
KW = set("self cls exp None True False and or not if else elif return for in is def class import from lambda while try except with as pass raise yield isinstance len str int list dict set tuple".split())

M = json.load((HERE / "map.json").open())
FILES, SETS, NAMES, DIAL, FX = M["files"], M["sets"], M["names"], M["dial"], M["fx"]
ALL = None


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
                    r = import_time(path, fi, n, rem, add, unit.get(str(n)))
                    if r is None: return None
                    sel |= r
    return sel


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
        dset = sset(DIAL[d])
        sel |= (dset & hits) if hits else dset
        return sel
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


def select_commit(patch_text):
    files = parse_patch(patch_text)
    if not files:
        return full()
    sel = set()
    for p, info in files.items():
        if info["binary"] or info["special"] or info["old"] != info["new"]:
            return full()
        if p.startswith("sqlglot/") and p.endswith(".py"):
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
            out[0] = out[0] + unknown  # tests this map never saw: always run them
        print(json.dumps({"commit": p.stem, "workers": [w for w in out if w]}))


if __name__ == "__main__":
    main()
