"""Real Bob Shell runs, Sept 27: why the subagent task kept going round until the cost cap.
- The same claim on the same diff was verified in one round and contradicted in the next ($2.51 run).
- "Tests must assert on the specific changed behavior" (D5) went to an audit in four runs; each audit cost Bob a
  round, and the Bob Shell audit never ran (no BOB_API_KEY in the MCP server).
- A docstring-only change was held to "Every behavior change must ship with a test that fails without the change"."""
import sys

from conftest import FakeJev, make_repo
from hallmonitor import bob, evidence as EV, gitutil, jev, receipts
from hallmonitor.store import Store
from test_bob_shell import REAL_RUN, fake_bob  # at import: before conftest stubs bob._run

CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'
D4 = "Every behavior change must ship with a test that fails without the change."
D5 = ("Tests must assert on the specific changed behavior; tests that only exercise the happy path or unrelated "
      "behavior do not satisfy the testing requirement.")
CLAIM = [{"claim": "Raised the limit in app/rl.py to 5.", "evidence": ["E1"]}]


def repo(tmp_path, *rules, mutants=2):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": "def limit():\n    return 0\n",
                                 "tests/__init__.py": ""},
                      config={"test_command": CMD, "max_mutants": mutants, "max_extreme_mutants": 0})
    for rule in rules:
        store.add_decision(rule, "docs/security-policy.pdf §4", kind="obligation")
    return store


def write(store, files):
    for path, text in files.items():
        (store.root / path).parent.mkdir(parents=True, exist_ok=True)
        (store.root / path).write_text(text, encoding="utf-8")
        EV.record({"tool": "write_file", "input": {"path": path, "content": text}}, store)


def raise_limit(store, test="    assert limit() == 5\n"):
    write(store, {"app/rl.py": "def limit():\n    return 5\n",
                  "tests/test_rl.py": "from app.rl import limit\n\ndef test_limit():\n" + test})


def row(result, text):
    return next(r for r in result["rows"] if text in r["claim"])


class Flipping(FakeJev):
    """Jev whose verdict on a claim changes from one call to the next, as it did in the real run."""

    def __init__(self, *verdicts, **overrides):
        self.verdicts, self.asked = list(verdicts), 0
        super().__init__(verdict=self.next_verdict, **overrides)

    def next_verdict(self, qid, state):
        self.asked += 1
        return self.verdicts[min(self.asked, len(self.verdicts)) - 1]


# ------------------------------------------------------------------ the same claim on the same diff

def test_the_same_claim_on_the_same_diff_keeps_its_verdict(tmp_path, monkeypatch):
    fake = Flipping(("supports", 0.97), ("contradicts", 0.97))
    monkeypatch.setattr(jev, "ask", fake)
    store = repo(tmp_path)
    raise_limit(store)
    first = receipts.verify(store, CLAIM)
    second = receipts.verify(store, CLAIM)
    assert fake.asked == 1  # the second round didn't ask Jev about the claim again
    assert row(first, "Raised")["state"] == row(second, "Raised")["state"] == "verified"
    assert row(second, "Raised")["code"] == "same_as_before" and second["status"] == "accept"


def test_resubmitting_a_contradicted_claim_doesnt_re_roll_jev(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", Flipping(("contradicts", 0.97), ("supports", 0.97), false=0.9))
    store = repo(tmp_path)
    raise_limit(store)
    assert row(receipts.verify(store, CLAIM), "Raised")["state"] == "contradicted"
    assert row(receipts.verify(store, CLAIM), "Raised")["state"] == "contradicted"


def test_a_new_edit_or_new_citations_are_judged_again(tmp_path, monkeypatch):
    fake = Flipping(("supports", 0.97))
    monkeypatch.setattr(jev, "ask", fake)
    store = repo(tmp_path)
    raise_limit(store)
    receipts.verify(store, CLAIM)
    receipts.verify(store, [{"claim": CLAIM[0]["claim"], "evidence": ["E1", "E2"]}])  # new citations
    assert fake.asked == 2
    write(store, {"app/rl.py": "def limit():\n    return 5  # per user\n"})  # a new diff
    receipts.verify(store, CLAIM)
    assert fake.asked == 3


# ------------------------------------------------------------------ D5: tests assert on the changed behavior

def test_tests_that_catch_the_change_satisfy_the_asserts_rule_in_code(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path, D5)
    raise_limit(store)
    rule = row(receipts.verify(store, CLAIM), "D1")
    assert (rule["state"], rule["code"], rule["tier"]) == ("verified", "fail_before", "code")
    assert "catch 1 of 1 sabotage mutants" in rule["detail"]


def test_tests_that_pass_without_the_change_break_the_asserts_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path, D5)
    raise_limit(store, test="    assert limit() is not None\n")
    assert row(receipts.verify(store, CLAIM), "D1")["state"] == "contradicted"


def test_a_test_that_fails_only_on_the_import_goes_to_jev(tmp_path, monkeypatch):
    """Without the change, app/rl2.py doesn't exist, so any test importing it fails there: that alone doesn't
    show it asserts on what changed. No mutant is caught, so code doesn't decide."""
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path, D5)
    write(store, {"app/rl2.py": "def limit():\n    return 5\n",
                  "tests/test_rl2.py": "from app.rl2 import limit\n\ndef test_limit():\n    assert True\n"})
    rule = row(receipts.verify(store, [{"claim": "Added app/rl2.py.", "evidence": ["E1"]}]), "D1")
    assert rule["tier"] != "code"


# ------------------------------------------------------------------ no behavior change

def test_a_docstring_only_change_needs_no_test(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("contradicts", 0.97)))
    store = repo(tmp_path, D4, D5)
    write(store, {"app/__init__.py": '"""Application package."""\n',
                  "app/rl.py": 'def limit():\n    """How many attempts a user gets."""\n    # none yet\n    return 0\n'})
    result = receipts.verify(store, [{"claim": "Added docstrings to app/.", "evidence": ["E1", "E2"]}])
    for rule in ("D1", "D2"):
        assert (row(result, rule)["state"], row(result, rule)["code"]) == ("verified", "not_applicable")


def test_code_added_or_removed_is_a_behavior_change(tmp_path):
    store = make_repo(tmp_path, {"app/rl.py": 'def limit():\n    """Old words."""\n    x = 1\n    return 0\n',
                                 ".gitignore": "*.pyc\n"})
    base = Store(store.root).session()["base"]
    (store.root / "app/rl.py").write_text('def limit():\n    """New words."""\n    return 0\n', encoding="utf-8")
    (store.root / ".gitignore").write_text("*.pyc\n.cache/\n", encoding="utf-8")
    changes = {f: c for f, c in gitutil.changes(store.root, base).items() if f in ("app/rl.py", ".gitignore")}
    lines = gitutil.behavior_lines(store.root, base, changes)
    assert lines == [("app/rl.py", -3)]  # `x = 1` went; the docstring and .gitignore don't count


# ------------------------------------------------------------------ the Bob Shell audit

def test_an_audit_that_failed_before_it_ran_isnt_an_audit(tmp_path, monkeypatch):
    store = repo(tmp_path)  # before the fake: it replaces subprocess.run for git too
    monkeypatch.setattr(bob, "_run", REAL_RUN)
    monkeypatch.setenv("BOB_API_KEY", "bob-key-value-123")
    fake_bob(monkeypatch, stdout="Usage: bob run ...", stderr="Error: bad key bob-key-value-123", code=1)
    assert bob.shell_audit(store.root, "Audit this claim independently: ...") is None
    logged = Store(store.root).dir.joinpath("bob_runs.jsonl").read_text(encoding="utf-8")
    assert "bad key <BOB_API_KEY>" in logged and "bob-key-value-123" not in logged
