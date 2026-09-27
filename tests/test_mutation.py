"""Extreme mutation (v4.2): pseudo-tested functions, found in a temporary copy of the repo. The end-to-end
tests run real pytest in a scratch repository; Jev is a fake."""
import ast
import hashlib
import textwrap

import pytest

from conftest import FakeJev, make_repo
from hallmonitor import evidence as EV, gitutil, jev, mutation, receipts, report
from hallmonitor.store import Store

LIMITS = '''"""Login limits."""


def is_allowed(attempts: int) -> bool:
    """True while the user is under the limit."""
    return attempts < 5


def label(attempts):
    if attempts >= 5:
        return "blocked"
    return f"{attempts} attempts"


class Counter:
    def __init__(self):
        self.n = 0

    def bump(self):
        self.n += 1
        return self.n
'''
TESTS = '''from app.limits import Counter, is_allowed, label


def test_limit():
    assert is_allowed(4) and not is_allowed(5)


def test_label_runs():
    label(3)  # vacuous: never checks the result


def test_counter():
    c = Counter()
    assert c.bump() == 1
'''


def fn(src, name):
    tree = ast.parse(textwrap.dedent(src))
    return tree, next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and n.name == name)


@pytest.mark.parametrize("src,expected", [
    ("def f() -> bool:\n    return check()\n", ["return False"]),
    ("def f(x) -> str:\n    return str(x)\n", ['return ""']),
    ("def f(x):\n    if x:\n        return 'a'\n    return f'{x}'\n", ['return ""']),
    ("def f(x):\n    if x:\n        return 1\n    return 2\n", ["return 0"]),
    ("def f(x):\n    return x > 3\n", ["return False"]),
    ("def f(x):\n    if x:\n        return 1\n    return 'a'\n", ["return None"]),
    ("def f(x):\n    def g():\n        return 'inner'\n    x.append(g)\n", ["return None"]),
    ("def f(xs):\n    for x in xs:\n        yield x\n", ["return", "yield  # an empty generator"]),
])
def test_default_return(src, expected):
    assert mutation.default_return(fn(src, "f")[1]) == expected


def test_mutate_keeps_the_docstring_and_the_rest_of_the_file():
    tree, node = fn(LIMITS, "is_allowed")
    new = mutation.mutate(LIMITS, node)
    assert '    """True while the user is under the limit."""\n    return False\n' in new
    assert "return attempts < 5" not in new and "def label(attempts):" in new
    ast.parse(new)
    assert mutation.mutate("def f(): return 1\n", fn("def f(): return 1\n", "f")[1]) is None  # one-line def


def changes_for(text, lines):
    return {"app/limits.py": {"status": "new", "added": [(n, text.splitlines()[n - 1]) for n in lines], "removed": 0},
            "tests/test_limits.py": {"status": "new", "added": [(1, "x")], "removed": 0}}


def test_targets_are_the_touched_functions_innermost_first():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "app").mkdir()
        (Path(d) / "app" / "limits.py").write_text(LIMITS)
        found = mutation.targets(d, changes_for(LIMITS, [1, 6, 10, 12, 17, 20, 21]))
    # line 1 is the module docstring; line 17 is __init__ (dunders are skipped); test files never count
    assert [(t["function"], t["body"]) for t in found] == \
        [("is_allowed", "return False"), ("label", 'return ""'), ("Counter.bump", "return None")]


@pytest.fixture
def repo(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/limits.py": "X = 1\n", "tests/test_x.py": "def test(): pass\n"},
                      config={"test_command": "python -m pytest -q", "max_mutants": 0})
    (tmp_path / "app" / "limits.py").write_text(LIMITS)
    (tmp_path / "tests" / "test_limits.py").write_text(TESTS)
    return store


def tree_hash(root):
    h = hashlib.sha1()
    for f in sorted(gitutil.git(root, "ls-files", "-co", "--exclude-standard").splitlines()):
        h.update(f.encode() + (root / f).read_bytes())
    return h.hexdigest()


def test_extreme_finds_the_pseudo_tested_function_without_touching_the_working_tree(repo):
    before = tree_hash(repo.root)
    changes = gitutil.changes(repo.root, repo.session()["base"])
    out = mutation.extreme(repo.root, changes, repo.config())
    assert out["extreme_mutants"] == 3
    assert [(p["function"], p["body_replaced_with"]) for p in out["pseudo_tested"]] == [("app/limits.py:label", 'return ""')]
    assert tree_hash(repo.root) == before


def test_extreme_respects_its_budget_and_a_failing_copy(repo):
    changes = gitutil.changes(repo.root, repo.session()["base"])
    assert mutation.extreme(repo.root, changes, {**repo.config(), "max_extreme_mutants": 1})["extreme_mutants"] == 1
    assert mutation.extreme(repo.root, changes, {**repo.config(), "max_extreme_mutants": 0})["extreme_note"] == "off"
    failing = {**repo.config(), "test_command": "python -c \"raise SystemExit(1)\""}
    assert mutation.extreme(repo.root, changes, failing) == \
        {"extreme_mutants": 0, "pseudo_tested": [], "extreme_note": "not run: the tests fail in a clean copy of the repo"}


def test_receipts_show_pseudo_tested_functions_to_jev_bob_and_the_user(repo, monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    EV.record({"tool": "write_file", "input": {"path": "app/limits.py", "content": LIMITS}}, repo)
    EV.record({"tool": "write_file", "input": {"path": "tests/test_limits.py", "content": TESTS}}, repo)
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"}, "output": "4 passed"}, repo)
    result = receipts.verify(repo, [{"claim": "Added tests that check label() for blocked users.",
                                     "evidence": ["E2", "E3"]}])
    assert result["sabotage"]["pseudo_tested"][0]["function"] == "app/limits.py:label"
    evidence = next(c["state"]["evidence"] for c in fake.calls if "verdict" in c["questions"])
    assert evidence["sabotage"]["pseudo_tested"][0]["body_replaced_with"] == 'return ""'  # Jev sees it for test claims
    assert "app/limits.py:label (line 9) has its whole body replaced" in receipts.message(result)
    assert "- tests still pass when app/limits.py:label" in (repo.dir / "receipts.md").read_text(encoding="utf-8")
    report.write_hall_pass(Store(repo.root))
    page = (repo.dir / "hall-pass.html").read_text(encoding="utf-8")
    assert "Pseudo-tested:</span>" in page and "app/limits.py:label" in page


# ---------------------------------------------------------------- sabotage runs in a copy too (v4.2)

def test_sabotage_runs_in_a_copy_and_leaves_the_working_tree_alone(repo, monkeypatch):
    before = tree_hash(repo.root)
    changes = gitutil.changes(repo.root, repo.session()["base"])
    seen = []
    real = gitutil.run_tests
    monkeypatch.setattr(gitutil, "run_tests", lambda root, *a, **k: seen.append(str(root)) or real(root, *a, **k))
    sab = gitutil.sabotage(repo.root, changes, "python -m pytest -q", max_mutants=4)
    assert sab["mutants"] == 4 and tree_hash(repo.root) == before
    assert seen and all(root != str(repo.root) for root in seen)  # every run, the baseline included, in the copy
    assert [(m["file"], m["line"]) for m in sab["survived"]] == [("app/limits.py", n) for n in (10, 11, 12)]  # label()


def test_sabotage_falls_back_to_the_working_tree_when_the_copy_cannot_pass(repo):
    (repo.root / ".gitignore").write_text("local_settings.py\n__pycache__/\n.pytest_cache/\n")
    (repo.root / "local_settings.py").write_text("DEBUG = True\n")  # ignored by git, so not in the copy
    (repo.root / "tests" / "test_settings.py").write_text("import local_settings\n\n\ndef test_it():\n    pass\n")
    changes = gitutil.changes(repo.root, repo.session()["base"])
    before = tree_hash(repo.root)
    sab = gitutil.sabotage(repo.root, changes, "python -m pytest -q", max_mutants=4)
    assert sab["mutants"] == 4 and [m["line"] for m in sab["survived"]] == [10, 11, 12]
    assert tree_hash(repo.root) == before  # restored after each in-place mutant, as before v4.2
