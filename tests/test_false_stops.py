"""Real Bob runs, Sept 27: the two causes of false stops left after the audit. A rule against new dependencies,
read at p=0.22-0.32, sent `python -m pytest -q` and a test edit to the user; and an edit at mismatch 0.26 went to
the user although an older intent of the same agent covered it. Jev is a fake."""
from conftest import FakeJev, make_repo
from hallmonitor import hook, jev, step
from hallmonitor.store import Store

DEPS = "Do not add third-party dependencies; use only the Python standard library."


def repo(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/service.py": "def login():\n    return 'ok'\n",
                                 "tests/test_service.py": "import pytest\nfrom app.service import login\n"})
    store.add_decision(DEPS, "docs/security-policy.pdf §3", kind="limit")
    return store


def test_code_tells_when_an_action_adds_no_dependency(tmp_path):
    root = repo(tmp_path).root
    edit = lambda path, content: {"tool": "apply_diff", "target": path, "content": content}  # noqa: E731
    intent = lambda files, commands: {"declared_intent": "x", "files": files, "commands": commands}  # noqa: E731
    assert step.adds_no_dependency(root, intent([], ["python -m pytest -q"]))
    assert not step.adds_no_dependency(root, intent([], ["pip install redis"]))
    assert not step.adds_no_dependency(root, intent(["app/service.py"], []))  # its edits are checked when made
    assert step.adds_no_dependency(root, {"tool": "execute_command", "target": "python -m pytest -q"})
    assert not step.adds_no_dependency(root, {"tool": "execute_command", "target": "uv add redis"})
    assert step.adds_no_dependency(root, edit("tests/test_service.py",
                                              "+import time, collections as c\n+import pytest\n+from . import x\n"
                                              "+from app.ratelimit import RateLimiter\n"))
    assert not step.adds_no_dependency(root, edit("app/service.py", "+import redis\n"))
    assert not step.adds_no_dependency(root, edit("requirements.txt", "+redis\n"))
    assert step.adds_no_dependency(root, edit("README.md", "+Uses redis? No.\n"))


def test_running_the_tests_isnt_sent_to_the_user_over_the_dependency_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(violates_D1=0.26))
    store = repo(tmp_path)
    step.declare_intent(store, "Run the unittest suite to check the limiter.", commands=["python -m unittest -q"])
    step.declare_intent(store, "Install the redis client for the counters.", commands=["pip install redis"])
    first, second = Store(store.root).session()["intents"]
    assert first["verdict"] == "approved"
    assert second["verdict"] != "approved"  # an install is still Jev's to judge, and 0.26 is not settled


def test_an_uncertain_mismatch_is_checked_against_the_agents_older_intents(tmp_path, monkeypatch):
    fits = lambda qid, state: 0.97 if "rate-limit test" in (state.get("stated_reason") or "") else 0.74  # noqa: E731
    monkeypatch.setattr(jev, "ask", FakeJev(matches_intent=fits))
    store = repo(tmp_path)
    for intent in ("Add a rate-limit test to tests/test_service.py", "Tidy the imports in tests/test_service.py"):
        store.add_intent({"agent": "main", "intent": intent, "files": ["tests/test_service.py"], "commands": [],
                          "verdict": "approved", "why": ""})
    code, _, err = hook.handle({"event": "PreToolUse", "tool": "apply_diff", "cwd": str(store.root),
                                "input": {"path": "tests/test_service.py",
                                          "diff": "+def test_sixth_attempt_is_refused():\n+    assert True\n"}})
    assert code == 0, err
    last = [e for e in store.events() if e["stage"] == "step"][-1]
    assert (last["action"], last["intent"]) == ("allow", "I1")
