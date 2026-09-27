"""The v4 loop links: a contradicted claim makes its files suspect (L4 -> L1), and a drifted subagent's
files need a fresh intent before the parent builds on them (L3 -> L1). Jev is a fake."""
from conftest import PASSING, FakeJev, make_repo
from hallmonitor import evidence as EV, hook, jev, receipts, step
from hallmonitor.store import Store


def repo(tmp_path):
    return make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n",
                                "app/ratelimit.py": "LIMIT = 5\n"},
                     config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})


def test_a_contradicted_claim_sends_the_next_intent_on_its_file_to_the_deep_look(tmp_path, monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    store = repo(tmp_path)
    (store.root / "app/service.py").write_text("def login():\n    return 'limited'\n", encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/service.py", "content": "..."}}, store)
    # app/ratelimit.py never changed, so this claim is contradicted in code
    receipts.verify(store, [{"claim": "Implemented the limiter in app/ratelimit.py.", "evidence": ["E1"]}])
    assert "app/ratelimit.py" in Store(store.root).session()["suspect_files"]

    msg = step.declare_intent(store, "Fix the limiter in app/ratelimit.py", files=["app/ratelimit.py"])
    judged = [c["state"] for c in fake.calls if c["state"].get("action", {}).get("declared_intent")][-1]
    assert "app/ratelimit.py" in judged["action"]["current_files_before_change"]  # the deep look reads it
    assert "app/ratelimit.py was named in a contradicted claim" in msg

    step.declare_intent(store, "Tidy login()", files=["app/service.py"])  # not suspect: no deep look
    judged = [c["state"] for c in fake.calls if c["state"].get("action", {}).get("declared_intent")][-1]
    assert "current_files_before_change" not in judged["action"]


def test_a_drifted_subagents_files_need_a_fresh_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(drifted=0.9))
    store = repo(tmp_path)
    brief = {"name": "general", "description": "Add the limiter to app/ratelimit.py."}
    assert hook.handle({"event": "PreToolUse", "tool": "spawn_subagent", "input": brief, "cwd": str(store.root)})[0] == 0
    (store.root / "app/ratelimit.py").write_text("LIMIT = 50\n", encoding="utf-8")  # the subagent's edit
    EV.record({"tool": "write_file", "input": {"path": "app/ratelimit.py", "content": "LIMIT = 50\n"}}, store)
    step.declare_intent(store, "Wire the limiter", files=["app/ratelimit.py"])  # declared before the return
    hook.handle({"event": "PostToolUse", "tool": "spawn_subagent", "input": brief, "cwd": str(store.root),
                 "tool_response": "Rewrote the whole auth module instead."})
    assert "app/ratelimit.py" in Store(store.root).session()["fresh_intent_needed"]

    edit = {"event": "PreToolUse", "tool": "write_file", "cwd": str(store.root),
            "input": {"path": "app/ratelimit.py", "content": "LIMIT = 5\n"}}
    code, _, err = hook.handle(edit)
    assert code == 2 and "declare_intent for app/ratelimit.py" in err
    step.declare_intent(store, "Restore the limit of 5 after checking the subagent's change",
                        files=["app/ratelimit.py"])
    assert hook.handle(edit)[0] == 0 and not Store(store.root).session()["fresh_intent_needed"]


def test_an_unsure_intent_is_restated_once_before_the_user_is_asked(tmp_path, monkeypatch):
    """v4 "restate" verdict: the first unsure intent goes back to the agent, the second to the user."""
    from hallmonitor import policy
    store = repo(tmp_path)
    unsure = policy.Decision("ask_human", {"ask_human": 1.0}, 0.0, risks={"violates_D1": 0.5})
    monkeypatch.setattr(step, "judge", lambda *a, **k: (unsure, {"violations": {}, "conflicts": {}, "tokens": 0,
                                                                 "pattern": None}))
    first = step.declare_intent(store, "Change things in app/service.py", files=["app/service.py"])
    assert "declare_intent again" in first
    assert Store(store.root).session()["intents"][-1]["verdict"] == "restate"
    assert [e["action"] for e in store.events() if e["stage"] == "intent"] == ["restate"]
    second = step.declare_intent(store, "Add a limit check to login() in app/service.py", files=["app/service.py"])
    assert "Ask the user" in second and Store(store.root).session()["intents"][-1]["verdict"] == "ask_human"
