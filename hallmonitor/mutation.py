"""Extreme mutation (v4.2): find pseudo-tested functions.

For each Python function whose lines the diff touches, the whole body is replaced with a default return
(the docstring is kept): `return None`, or `return False` / `0` / `""` when the function's annotation or
its existing returns make the type obvious. If the tests still pass, nothing they check depends on that
function: it is pseudo-tested (Niedermayr et al., "Will my tests tell me if I break this code?", 2016;
Descartes does the same for Java). Where gitutil.sabotage breaks one line, this removes the function.

Every mutant runs in a temporary copy of the repository (gitutil.copy_tree), never in the working tree.
The copy is checked first: if the tests fail there unmutated, nothing is reported.

Budget (config): max_extreme_mutants (default 3; 0 turns it off), extreme_timeout seconds per test run
(default 60), and 3x that for the whole pass. Receipts adds the result to the sabotage evidence, so it
reaches Jev exactly where sabotage results do (claims about tests, and deep looks).
"""
import ast
import tempfile
import time
from pathlib import Path

from . import gitutil

DEFAULT_BY_TYPE = {"bool": "False", "int": "0", "float": "0", "str": '""'}


def _own_nodes(fn):
    """Nodes inside `fn`, not counting nested functions, lambdas and classes."""
    todo = list(fn.body)
    while todo:
        n = todo.pop()
        yield n
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            todo.extend(ast.iter_child_nodes(n))


def _type_of(value):
    if isinstance(value, ast.Constant):
        v = value.value
        return "bool" if isinstance(v, bool) else "int" if isinstance(v, int) else \
            "float" if isinstance(v, float) else "str" if isinstance(v, str) else None
    if isinstance(value, (ast.Compare,)) or (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)):
        return "bool"
    if isinstance(value, ast.JoinedStr):
        return "str"
    return None


def default_return(fn):
    """The body that replaces `fn`'s: a list of statements as source text."""
    own = list(_own_nodes(fn))
    if any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in own):
        return ["return", "yield  # an empty generator"]
    ann = fn.returns
    if isinstance(ann, ast.Name) and ann.id in DEFAULT_BY_TYPE:
        return [f"return {DEFAULT_BY_TYPE[ann.id]}"]
    types = {_type_of(n.value) for n in own if isinstance(n, ast.Return) and n.value is not None}
    if len(types) == 1 and None not in types:
        return [f"return {DEFAULT_BY_TYPE[types.pop()]}"]
    return ["return None"]


def _is_docstring(stmt):
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _trivial(fn):
    """Bodies a default return can't meaningfully change: pass, ..., return None, raise NotImplementedError."""
    body = [s for s in fn.body if not _is_docstring(s)]
    if not body:
        return True
    if len(body) > 1:
        return False
    s = body[0]
    return isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)) or \
        (isinstance(s, ast.Return) and (s.value is None or (isinstance(s.value, ast.Constant) and s.value.value is None))) \
        or isinstance(s, ast.Raise)


def _functions(tree):
    """(qualified name, node) for every function and method, outermost first."""
    out = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((prefix + child.name, child))
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)
    visit(tree, "")
    return out


def mutate(text, fn):
    """`text` with `fn`'s body (after its docstring) replaced by its default return, or None if that
    can't be done cleanly (a one-line def, or a result that doesn't parse)."""
    body = [s for s in fn.body if not _is_docstring(s)]
    if not body or body[0].lineno == fn.lineno:
        return None
    lines = text.splitlines(keepends=True)
    first = min([body[0].lineno] + [d.lineno for d in getattr(body[0], "decorator_list", [])])
    last = fn.end_lineno
    indent = lines[first - 1][:len(lines[first - 1]) - len(lines[first - 1].lstrip())]
    new = "".join(lines[:first - 1] + [f"{indent}{s}\n" for s in default_return(fn)] + lines[last:])
    try:
        ast.parse(new)
    except SyntaxError:
        return None
    return new


def targets(root, changes):
    """Functions whose lines the diff touches, innermost first per touched line, in diff order."""
    out = []
    for path, c in changes.items():
        if not path.endswith(".py") or gitutil.is_test(path):
            continue
        try:
            text = (Path(root) / path).read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue
        funcs = _functions(tree)
        seen = []
        for lineno, _ in c["added"]:
            inside = [(name, fn) for name, fn in funcs
                      if min([fn.lineno] + [d.lineno for d in fn.decorator_list]) <= lineno <= fn.end_lineno]
            if not inside:
                continue
            name, fn = max(inside, key=lambda x: x[1].lineno)  # the innermost
            if name in seen or fn.name.startswith("__") or _trivial(fn):
                continue
            new = mutate(text, fn)
            if new is None:
                continue
            seen.append(name)
            out.append({"file": path, "function": name, "line": fn.lineno,
                        "body": "; ".join(default_return(fn)).split("  #")[0], "mutated": new})
    return out


def extreme(root, changes, cfg):
    """Run the extreme mutants. Returns the keys Receipts adds to its sabotage evidence."""
    limit = int(cfg.get("max_extreme_mutants", 3))
    timeout = float(cfg.get("extreme_timeout", 60))
    found = targets(root, changes)[:max(limit, 0)]
    out = {"extreme_mutants": 0, "pseudo_tested": []}
    if not found:
        return {**out, "extreme_note": "no changed functions to test" if limit > 0 else "off"}
    deadline = time.time() + 3 * timeout
    with tempfile.TemporaryDirectory(prefix="hm-extreme-") as tmp:
        gitutil.copy_tree(root, tmp)
        if not gitutil.run_tests(tmp, cfg["test_command"], timeout, copy=True)["passed"]:
            return {**out, "extreme_note": "not run: the tests fail in a clean copy of the repo"}
        for t in found:
            if time.time() > deadline:
                out["extreme_note"] = "time budget used up"
                break
            path = Path(tmp) / t["file"]
            original = path.read_text(encoding="utf-8")
            path.write_text(t["mutated"], encoding="utf-8")
            try:
                still_pass = gitutil.run_tests(tmp, cfg["test_command"], timeout, copy=True)["passed"]
            finally:
                path.write_text(original, encoding="utf-8")
            out["extreme_mutants"] += 1
            if still_pass:
                out["pseudo_tested"].append({"function": f"{t['file']}:{t['function']}", "line": t["line"],
                                             "body_replaced_with": t["body"], "tests_still_pass": True})
    return out


def lines(sab):
    """Evidence lines for Bob and for receipts.md."""
    return [f"tests still pass when {p['function']} (line {p['line']}) has its whole body replaced with "
            f"`{p['body_replaced_with']}`: it is pseudo-tested" for p in sab.get("pseudo_tested") or []]
