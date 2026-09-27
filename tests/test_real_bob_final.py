"""Final real Bob Shell run, Sept 27: the task with two parallel subagents ended STUCK although the main
agent's claims verified. A tidy-up subagent's three submissions were held to every project rule and used up
the task's send-backs, and "tests must fail without the change" went to Jev although fail-before answers it."""
import sys

from conftest import FakeJev, make_repo
from hallmonitor import evidence as EV, jev, receipts
from hallmonitor.store import Store

CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'
RULE = "Every behavior change must ship with a test that fails without the change."


def repo(tmp_path):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": "def limit():\n    return 0\n",
                                 "tests/__init__.py": ""},
                      config={"test_command": CMD, "max_mutants": 0, "max_extreme_mutants": 0})
    store.add_decision(RULE, "docs/security-policy.pdf §4", kind="obligation")
    return store


def change(store, test_body):
    for path, text in (("app/rl.py", "def limit():\n    return 5\n"), ("tests/test_rl.py", test_body)):
        (store.root / path).write_text(text, encoding="utf-8")
        EV.record({"tool": "write_file", "input": {"path": path, "content": text}}, store)


def test_a_subagents_submission_is_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("says_nothing", 0.9)))
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    for _ in range(3):
        r = receipts.verify(store, [{"claim": "Tidied app/rl.py.", "evidence": ["E1"]}], agent="tidy-subagent")
        assert not any("D1" in row["claim"] for row in r["rows"])  # the task's rules wait for the main agent
    s = Store(store.root).session()
    assert s["send_backs"] == 0 and s["agent_send_backs"]["tidy-subagent"] >= 2


def test_the_fails_without_the_change_rule_is_decided_by_fail_before(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    rows = receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])["rows"]
    rule = next(r for r in rows if "D1" in r["claim"])
    assert (rule["state"], rule["code"], rule["tier"]) == ("verified", "fail_before", "code")


def test_a_test_that_passes_without_the_change_breaks_that_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() is not None\n")
    rows = receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])["rows"]
    assert next(r for r in rows if "D1" in r["claim"])["state"] == "contradicted"


def test_a_subagents_verified_part_doesnt_make_the_task_verified(tmp_path, monkeypatch):
    """Confirming real Bob run: subagent-B's docstring claims verified, the main agent never submitted, and the
    Hall Pass and the CI gate read the task as VERIFIED."""
    from hallmonitor import report
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    change(store, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    receipts.verify(store, [{"claim": "Added a docstring to app/rl.py.", "evidence": ["E1"]}], agent="subagent-B")
    assert [e["agent"] for e in store.events() if e["stage"] == "receipts"] == ["subagent-B"]
    assert receipts.task_rounds(store.events()) == []
    _, summary = report.write_hall_pass(store)
    assert "receipts: IN PROGRESS" in summary
    receipts.verify(store, [{"claim": "Raised the limit in app/rl.py.", "evidence": ["E1"]}])
    assert [e["agent"] for e in receipts.task_rounds(store.events())] == ["main"]


def test_an_edit_is_matched_to_the_parallel_agent_whose_intent_it_fits(tmp_path, monkeypatch):
    """Confirming real run: subagent-A's limiter edit to app/service.py was checked against subagent-B's newer
    docstring intent for the same file, blocked as a mismatch, and B's intent revoked."""
    from hallmonitor import hook
    fits = lambda qid, state: 0.1 if "docstring" in (state.get("stated_reason") or "") else 0.95  # noqa: E731
    monkeypatch.setattr(jev, "ask", FakeJev(matches_intent=fits))
    store = repo(tmp_path)
    service = store.root / "app" / "service.py"
    service.write_text("def login():\n    return 'ok'\n", encoding="utf-8")
    for agent, intent in (("subagent-A", "Wire the rate limiter into login() in app/service.py"),
                          ("subagent-B", "Improve the module docstring in app/service.py")):
        store.add_intent({"agent": agent, "intent": intent, "files": ["app/service.py"], "commands": [],
                          "verdict": "approved", "why": ""})
    edit = {"event": "PreToolUse", "tool": "write_file", "cwd": str(store.root),
            "input": {"path": "app/service.py", "content": "from app.rl import limit\n\ndef login():\n    limit()\n"}}
    code, _, err = hook.handle(edit)
    assert code == 0, err
    step_event = [e for e in store.events() if e["stage"] == "step"][-1]
    assert step_event["action"] == "allow" and step_event["intent"] == "I1"  # subagent-A's intent
    assert all(it["verdict"] == "approved" for it in Store(store.root).session()["intents"])  # nothing revoked
