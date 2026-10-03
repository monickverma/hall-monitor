"""L0: the certified plan gate, and decisions recorded, superseded and rejected by authority. Jev is a fake."""
from conftest import FakeJev, never
from hallmonitor import brief, jev, ledger, plan, step
from hallmonitor.store import Store

CERTIFIED = """# Plan
## Premises
- login() in app/service.py is the only entry point.
## Files to change
1. Add app/ratelimit.py with an in-memory RateLimiter.
2. Call the limiter from login() in app/service.py.
## Tests
3. Add tests/test_ratelimit.py proving the 6th attempt is refused.
"""


def test_a_plan_without_its_certificate_is_sent_back_without_asking_jev(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)  # no decisions yet: nothing for Jev to check
    store = Store(tmp_path)
    code, _, err = plan.check(store, "# Plan\n1. Add the limiter.\n2. Wire it in.\n")
    assert code == 2 and "missing certificate sections: premises, files, tests" in err
    assert plan.check(store, CERTIFIED) == (0, "", "")
    assert [e["missing_sections"] for e in store.events() if e["stage"] == "plan"] == \
        [["premises", "files", "tests"], []]


def test_a_plan_step_that_breaks_a_limit_is_blocked(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.add_decision("Keep the counters in memory; no Redis.", "user", kind="limit")
    store.add_decision("Every change ships with a test.", "user", kind="obligation")  # Receipts checks this one
    fake = FakeJev(s0_D1=0.97)  # step 0 contradicts D1
    monkeypatch.setattr(jev, "ask", fake)
    text = CERTIFIED.replace("in-memory RateLimiter", "RateLimiter that keeps counters in Redis")
    code, _, err = plan.check(store, text)
    assert code == 2 and 'contradicts D1 "Keep the counters in memory; no Redis."' in err
    assert not any(q.endswith("_D2") for q in fake.calls[-1]["questions"])  # obligations aren't plan-checked


def test_a_plan_md_write_goes_through_the_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    store = Store(tmp_path)
    code, _, err = step.pre_tool({"tool": "write_file", "input": {"path": str(tmp_path / "PLAN.md"),
                                                                "content": "# Plan\n1. Do it.\n"}}, store)
    assert code == 2 and "plan gate" in err


def test_decisions_are_recorded_superseded_and_protected_by_authority(tmp_path, monkeypatch):
    from conftest import make_repo
    store = make_repo(tmp_path, {"docs/policy.pdf": "policy\n"})  # a document counts only if the repo tracks it
    monkeypatch.setattr(jev, "ask", FakeJev(scope="limit"))
    out = ledger.record_decision(store, "Keep the counters in memory.", "docs/policy.pdf §2", quote="In memory.")
    assert out == "Recorded D1 (limit, checked on every action): Keep the counters in memory."
    monkeypatch.setattr(jev, "ask", FakeJev(scope="limit", contra=0.95))  # contradicts every active decision
    s = store.session()
    s["user_rule_sentences"] = ["Actually, use Redis for the counters."]  # only a rule the user said is the user's
    store.save_session(s)
    out = ledger.record_decision(store, "Use Redis for the counters.", "user")
    assert "supersedes D1" in out  # the user has at least a document's authority
    assert [d["id"] for d in store.active_decisions()] == ["D2"]
    out = ledger.record_decision(store, "Keep the counters in memory after all.", "agent")
    assert out.startswith("REJECTED: contradicts D2") and "higher authority" in out  # the agent can't override
    assert [d["id"] for d in store.active_decisions()] == ["D2"]
    assert ledger.list_decisions(store) == "D2 [limit, from user]: Use Redis for the counters."
    assert [e["action"] for e in store.events() if e["stage"] == "ledger"] == ["record", "record", "reject"]


def test_obligations_are_checked_on_the_finished_work(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(jev, "ask", FakeJev(scope="obligation"))
    out = ledger.record_decision(store, "Every behavior change ships with a test.", "docs/policy.pdf §4")
    assert "obligation, checked on the finished work (Receipts)" in out
    assert store.active_decisions(kind="limit") == [] and len(store.active_decisions(kind="obligation")) == 1


def test_a_decision_stated_in_a_prompt_supersedes_the_one_it_contradicts(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.add_decision("Keep the counters in memory.", "user")
    monkeypatch.setattr(jev, "ask", FakeJev(decision_1=0.95, contra_1_D1=0.9))
    code, out, _ = brief.user_prompt({"prompt": "Add a login limit to login(). Store the counters in Redis instead."},
                                     store)
    assert code == 0 and "New decisions recorded: D2 (replaces D1)" in out
    assert [(d["id"], d["supersedes"]) for d in store.active_decisions()] == [("D2", "D1")]


def test_agents_md_decisions_are_imported_once(tmp_path, monkeypatch):
    (tmp_path / "AGENTS.md").write_text("# Agents\n## Decisions\n- Never modify app/auth.py.\n"
                                        "- Every change ships with a test.\n## Other\n- not a decision\n")
    monkeypatch.setattr(jev, "ask", FakeJev(scope_1="obligation"))
    store = Store(tmp_path)
    code, out, _ = brief.session_start({}, store)
    assert "D1: Never modify app/auth.py." in out and "D2: Every change ships with a test. (checked when you finish)" in out
    monkeypatch.setattr(jev, "ask", never)
    brief.session_start({}, store)  # the ledger isn't empty any more: nothing re-imported
    assert len(store.ledger()) == 2
