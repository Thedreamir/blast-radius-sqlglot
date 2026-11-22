"""Adds, for every plain expression class (not a function class), the tests that can create an instance of it.
Usage: build_creators.py MAP_JSON SQLGLOT_DIR
A mention of a class name is harmless for the class's own attributes when it is a dict key, an isinstance test, a
comparison or an annotation: none of those read the class's attributes or build an instance. Every other mention
(a call, an argument, an attribute read, a string equal to the name) can. Mentions in code that runs at import mark
the class as read at import (then the selector keeps the broad path); mentions in code that runs later contribute
the tests that executed that statement. Tests whose source mentions the name are always included.
Output: M["cls"] (bases), M["clsline"] (class body statement spans), M["creators"] {name: {"tests": [...], "imp": bool}}"""
import ast, glob, json, os, sys
mp, sg = sys.argv[1:3]
M = json.load(open(mp))
FILES = M["files"]
SETS = M["sets"]

# class graph and class body statements
cls, clsline = {}, {}
for f in sorted(glob.glob(os.path.join(sg, "sqlglot", "expressions", "*.py"))):
    rel = os.path.relpath(f, sg)
    tree = ast.parse(open(f, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            cls[node.name] = [b.id if isinstance(b, ast.Name) else b.attr for b in node.bases if isinstance(b, (ast.Name, ast.Attribute))]
            body = [[s.lineno, s.end_lineno] for s in node.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
            clsline.setdefault(rel, []).append([node.lineno, node.end_lineno, node.name, body])


def func_family(name):
    seen, todo = set(), list(cls.get(name, []))
    while todo:
        b = todo.pop()
        if b not in seen:
            seen.add(b); todo.extend(cls.get(b, []))
    return seen


names = {n for n in cls if n != "Func" and "Func" not in func_family(n)}
tests_of = {n: set() for n in names}
imp_read = {n: False for n in names}

# tests whose own source mentions the name
tests = json.load(open(os.path.join(sg, "..", "sample_tests.json")))["tests"] if False else None
ids = M["ids"]
src_by_file = {}
for i, tid in enumerate(ids):
    f = tid.split("::")[0]
    if f not in src_by_file:
        src_by_file[f] = open(os.path.join(sg, f), encoding="utf-8").read()
seg = {}
for f, src in src_by_file.items():
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for fn in node.body:
                if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    seg[(f, node.name, fn.name)] = ast.get_source_segment(src, fn) or ""
        elif isinstance(node, ast.FunctionDef):
            seg.setdefault((f, None, node.name), ast.get_source_segment(src, node) or "")
for i, tid in enumerate(ids):
    p = tid.split("::")
    s = (seg.get((p[0], p[1], p[2])) if len(p) == 3 else seg.get((p[0], None, p[1]))) or ""
    s = (s + " " + os.path.basename(p[0])).lower()
    for n in names:
        if n.lower() in s:
            tests_of[n].add(i)


def mark_annotations(tree):
    ann = set()
    def add(n):
        if n is not None:
            for x in ast.walk(n): ann.add(id(x))
    for n in ast.walk(tree):
        if isinstance(n, ast.arg): add(n.annotation)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): add(n.returns)
        elif isinstance(n, ast.AnnAssign): add(n.annotation)
    return ann


def benign(node, parents, ann):
    if id(node) in ann:
        return True
    p = parents.get(id(node))
    if isinstance(p, ast.Dict) and any(k is node for k in p.keys):
        return True
    if isinstance(p, ast.Compare):
        return True
    q = p
    if isinstance(p, ast.Tuple):
        q = parents.get(id(p))
        if isinstance(q, ast.Compare):
            return True
    if isinstance(q, ast.Call) and isinstance(q.func, ast.Name) and q.func.id in ("isinstance", "issubclass") and q.args and q.args[0] is not node and q.args[0] is not p:
        return True
    return False


def mention_name(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return node.attr
    if isinstance(node, ast.Constant) and isinstance(node.value, str): return node.value
    return None


for f in sorted(glob.glob(os.path.join(sg, "sqlglot", "**", "*.py"), recursive=True)):
    rel = os.path.relpath(f, sg)
    fi = FILES.get(rel)
    text = open(f, encoding="utf-8").read()
    tree = ast.parse(text)
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n): parents[id(c)] = n
    ann = mark_annotations(tree)
    imp = set(fi["imp"]) | set(fi["ic"]) if fi else None
    for node in ast.walk(tree):
        nm = mention_name(node)
        if nm not in names:
            continue
        # a class statement's own base list and the defining class header are not reads
        p = parents.get(id(node))
        if isinstance(p, ast.ClassDef) and node in p.bases:
            continue
        if isinstance(p, ast.Attribute) and p.value is node:
            pass
        if isinstance(node, ast.Attribute) and isinstance(parents.get(id(node)), ast.Attribute) and False:
            pass
        if isinstance(node, ast.Name) and isinstance(p, ast.Attribute) and p.value is node and nm in names and False:
            pass
        if isinstance(node, ast.Name) and isinstance(p, ast.Attribute):
            # `exp.Foo` is the Attribute node itself; a bare module name is not a mention
            pass
        if benign(node, parents, ann):
            continue
        line = node.lineno
        if fi is None:
            imp_read[nm] = True
            continue
        if line in imp:
            imp_read[nm] = True
            continue
        u = fi["unit"].get(str(line))
        s, e = (u[0], u[1]) if u else (line, line)
        for l in range(s, e + 1):
            v = fi["cov"].get(str(l))
            if v is not None:
                tests_of[nm].update(SETS[v])

M["cls"], M["clsline"] = cls, clsline
M["creators"] = {n: {"tests": sorted(tests_of[n]), "imp": imp_read[n]} for n in names}
json.dump(M, open(mp, "w"), separators=(",", ":"))
print(len(names), "plain classes;", sum(1 for n in names if not imp_read[n]), "without import-time reads")
t = M["creators"].get("TriggerProperties")
print("TriggerProperties", t and (len(t["tests"]), t["imp"]))
