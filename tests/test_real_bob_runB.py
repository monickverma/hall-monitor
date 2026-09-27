"""Real Bob Shell run, Sept 27 (the runbook's task with two parallel subagents, after /decisions in the same
repo). It ended STUCK at its cost cap for three reasons fixed here. Jev is a fake."""
from conftest import PASSING, FakeJev, make_repo
from hallmonitor import brief, evidence as EV, hook, jev, receipts, step
from hallmonitor.store import Store


def repo(tmp_path):
    return make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n",
                                "app/auth.py": "def check():\n    return False\n",
                                "scripts/seed.py": "print('seed')\n"},
                     config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})


def test_a_cd_into_the_repo_doesnt_hide_a_test_run_or_a_declared_command(tmp_path, monkeypatch):
    """Bob ran `cd <workspace> && python -m pytest ...`: no test run counted, and declared commands were
    blocked as undeclared."""
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    root = store.root.resolve().as_posix()
    assert EV.repo_command(store.root, f"cd {root} && python -m pytest -q") == "python -m pytest -q"
    assert EV.repo_command(store.root, f'cd "{root}/app"; ls') == "ls"
    assert EV.repo_command(store.root, "cd /etc && cat passwd") == "cd /etc && cat passwd"  # outside: kept
    EV.record({"tool": "execute_command", "input": {"command": f"cd {root} && python -m pytest -q"},
               "output": "3 passed in 0.01s"}, store)
    assert store.evidence()[0]["kind"] == "test"
    step.declare_intent(store, "Seed the demo data", commands=["python scripts/seed.py"])
    code, _, err = hook.handle({"event": "PreToolUse", "tool": "execute_command", "cwd": root,
                                "input": {"command": f"cd {root} && python scripts/seed.py"}})
    assert code == 0, err


def test_a_rule_about_changes_to_a_file_holds_when_that_file_didnt_change(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    store.add_decision("Changes to app/auth.py require a security team review before they are merged.",
                       "docs/security-policy.pdf §2", kind="obligation")
    (store.root / "app/service.py").write_text("def login():\n    return 'limited'\n", encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/service.py", "content": "..."}}, store)
    rows = receipts.verify(store, [{"claim": "Limited login() in app/service.py.", "evidence": ["E1"]}])["rows"]
    rule = next(r for r in rows if "D1" in r["claim"])
    assert (rule["state"], rule["code"], rule["tier"]) == ("verified", "not_applicable", "code")

    (store.root / "app/auth.py").write_text("def check():\n    return True\n", encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/auth.py", "content": "..."}}, store)
    rows = receipts.verify(store, [{"claim": "Limited login() in app/service.py.", "evidence": ["E1"]}])["rows"]
    assert next(r for r in rows if "D1" in r["claim"])["tier"] != "code"  # it applies now: judged on evidence


def test_a_new_task_starts_its_own_receipts_rounds(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(new_task=0.9, decision=0.1))
    store = repo(tmp_path)
    s = store.session()
    s.update({"goal": "Record the policy's rules", "send_backs": 2, "suspect_files": {"app/auth.py": "x"},
              "uncited_retry_used": True})
    store.save_session(s)
    brief.user_prompt({"event": "UserPromptSubmit", "prompt": "Add a per-user login limit to app/service.py."}, store)
    s = Store(store.root).session()
    assert (s["send_backs"], s["suspect_files"], s["uncited_retry_used"]) == (0, {}, False)
