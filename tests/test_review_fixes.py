"""Fixes from the PR #1 review: protected paths, Jev refusals everywhere, audit notes, notes delivery.
No real Jev calls: jev.ask is replaced by a fake that refuses or answers on cue."""
import subprocess

import pytest

from hallmonitor import evidence as EV, hook, jev, mcp_server, receipts, step
from hallmonitor.store import Store, is_protected, rel_path


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=root,
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "service.py").write_text("def login():\n    return 'ok'\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    store = Store(tmp_path)
    (store.dir / "config.json").write_text('{"test_command": "python -c \\"print(\'1 passed\')\\"", "max_mutants": 1}')
    s = store.session()
    s["base"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    store.save_session(s)
    return tmp_path


def refuse(*a, **k):
    raise jev.JevRefused("403")


def never(*a, **k):
    raise AssertionError("Jev must not be asked")


# ---------------------------------------------------------------- protected paths

def test_protected_paths_are_canonicalized(repo):
    for path in (".hallmonitor/config.json", "./.bob/settings.json", "app/../.hallmonitor/config.json",
                 str(repo / ".bob" / "x.json"), ".hallmonitor"):
        assert is_protected(repo, path), path
    assert is_protected(repo, "../.hallmonitor/config.json", base=repo / "app")  # from a subfolder
    for path in ("app/service.py", ".bobby/x", "app/.hallmonitor.py"):
        assert not is_protected(repo, path), path


def test_protected_edit_is_blocked_before_jev(repo, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    code, _, err = step.pre_tool({"tool": "write_file", "cwd": str(repo),
                                  "input": {"path": "app/../.hallmonitor/config.json", "content": "{}"}}, Store(repo))
    assert code == 2 and "can't be edited" in err


# ---------------------------------------------------------------- refusals

def test_refused_edit_asks_the_user_even_with_an_approved_intent(repo, monkeypatch):
    store = Store(repo)
    store.add_intent({"agent": "main", "intent": "edit login", "files": ["app/service.py"], "commands": ["python -m pytest -q"],
                      "verdict": "approved", "why": ""})
    monkeypatch.setattr(jev, "ask", refuse)
    code, _, err = step.pre_tool({"tool": "write_file", "input": {"path": "app/service.py", "content": "x"}}, store)
    assert code == 2 and "ask the user" in err
    # the exact command the approved intent declared was already judged, so code lets it run
    code, _, _ = step.pre_tool({"tool": "execute_command", "input": {"command": "python -m pytest -q"}}, store)
    assert code == 0


def test_refusals_never_fall_through_the_generic_error_path(repo, monkeypatch):
    Store(repo).add_decision("Keep the counters in memory; no Redis.", "user")  # so the plan gate asks Jev
    monkeypatch.setattr(jev, "ask", refuse)
    plan = "# Plan\n## Premises\n- x\n## Files to change\n1. app/service.py: add it\n## Tests\n2. a test\n"
    code, _, err = hook.handle({"event": "PreToolUse", "cwd": str(repo), "tool": "write_file",
                                "input": {"path": "PLAN.md", "content": plan}})
    assert code == 2 and "couldn't check" in err
    code, out, _ = hook.handle({"event": "UserPromptSubmit", "cwd": str(repo), "prompt": "Add a limiter. Keep it in memory."})
    assert code == 0 and "Couldn't check this prompt" in out
    assert "couldn't check this (record_decision)" in mcp_server.call(
        "record_decision", {"text": "No Redis.", "source": "user"}, Store(repo))


def test_code_verdicts_still_apply_when_jev_refuses(repo, monkeypatch):
    store = Store(repo)
    monkeypatch.setattr(jev, "ask", refuse)
    (repo / "app" / "ratelimit.py").write_text("LIMIT = 5\n")
    EV.record({"tool": "write_file", "input": {"path": "app/ratelimit.py", "content": "LIMIT = 5\n"}}, store)
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"}, "output": "1 passed"}, store)
    result = receipts.verify(store, [
        {"claim": "app/service.py was not modified.", "evidence": []},
        {"claim": "Wired the limiter into login() in app/service.py.", "evidence": ["E2"]},
        {"claim": "All tests pass.", "evidence": ["E2"]}])
    states = {r["claim"][:12]: (r["state"], r["code"]) for r in result["rows"]}
    assert states["app/service."] == ("verified", "code")
    assert states["Wired the li"] == ("contradicted", "diff_mismatch")
    assert states["All tests pa"] == ("cant_check", "jev_refused")


# ---------------------------------------------------------------- audit notes can't skip a round

def fake_contradicts(state, questions):
    answers = {}
    for qid in questions:
        if qid.startswith("kind_"):
            answers[qid] = {"choice": "implemented", "probabilities": {}, "confidence": 1.0}
        elif qid == "verdict":
            answers[qid] = {"choice": "contradicts", "confidence": 0.95,
                            "probabilities": {"supports": 0.02, "says_nothing": 0.03, "contradicts": 0.95}}
        elif qid == "false":
            answers[qid] = {"noul": 0.95}
        elif qid == "risk":
            answers[qid] = {"score": 1.0, "confidence": 1.0, "probabilities": {"1": 1.0}}
    return answers, {"input_tokens": 1, "output_tokens": 0, "model": "fake"}


def test_unrequested_audit_notes_do_not_skip_a_send_back(repo, monkeypatch):
    store = Store(repo)
    monkeypatch.setattr(jev, "ask", fake_contradicts)
    (repo / "app" / "ratelimit.py").write_text("LIMIT = 5\n")
    EV.record({"tool": "write_file", "input": {"path": "app/ratelimit.py", "content": "LIMIT = 5\n"}}, store)
    claim = [{"claim": "Implemented the limiter in app/ratelimit.py.", "evidence": ["E1"]}]
    statuses = [receipts.verify(store, claim, audit_notes={"0": "looks fine to me"})["status"] for _ in range(3)]
    assert statuses == ["send_back", "send_back", "stuck"]


# ---------------------------------------------------------------- notes reach Bob on every tool

def test_notes_are_delivered_on_every_mcp_tool(repo):
    store = Store(repo)
    store.queue_note("Stall 1 (looping on one failure).")
    assert mcp_server.call("list_decisions", {}, store).startswith("Hall Monitor notes before you continue:")


# ---------------------------------------------------------------- edits under an approved intent

def fake_low_risk(asked):
    def ask(state, questions):
        asked.append(set(questions))
        out = {}
        for qid in questions:
            if qid == "on_task":
                out[qid] = {"score": 3.0, "confidence": 1.0, "probabilities": {"0": 0.0, "1": 0.0, "2": 0.05, "3": 0.95}}
            elif qid == "rationalization":
                out[qid] = {"choice": "none", "confidence": 1.0, "probabilities": {"none": 1.0}}
            else:  # destructive, violates_*, matches_intent, conflict_*
                out[qid] = {"noul": 0.97 if qid == "matches_intent" else 0.03}
        return out, {"input_tokens": 1, "output_tokens": 0, "model": "fake"}
    return ask


def test_edit_under_approved_intent_skips_on_task_and_clashes(repo, monkeypatch):
    store = Store(repo)
    store.add_intent({"agent": "subagent-A", "intent": "wire the limiter", "files": ["app/service.py"], "commands": [],
                      "verdict": "approved", "why": ""})  # another agent's active work: the case that crashed
    store.add_intent({"agent": "main", "intent": "write tests", "files": ["tests/test_x.py"], "commands": [],
                      "verdict": "approved", "why": ""})
    asked = []
    monkeypatch.setattr(jev, "ask", fake_low_risk(asked))
    code, _, _ = step.pre_tool({"tool": "write_file", "input": {"path": "tests/test_x.py", "content": "def test(): pass"}},
                               store)
    assert code == 0
    assert not any(q.startswith("conflict_") or q == "on_task" for q in asked[-1])
    assert "matches_intent" in asked[-1]
    assert not [e for e in store.events() if e.get("stage") == "error"]


# ---------------------------------------------------------------- paths as Bob sends them

def test_paths_are_compared_repo_relative(repo):
    for path in (str(repo / "app" / "service.py"), "app\\service.py", "./app/service.py", "app/../app/service.py"):
        assert rel_path(repo, path) == "app/service.py", path
    assert rel_path(repo, "service.py", base=repo / "app") == "app/service.py"  # from a subfolder
    assert is_protected(repo, rel_path(repo, "../.bob/x.json", base=repo / "app"))  # still caught once resolved


def test_absolute_tool_path_matches_a_relative_declared_file(repo, monkeypatch):
    """Bob's edit tools send absolute paths while declare_intent gets relative ones (preflight, Sept 27):
    the edit must be judged under the declared intent, not blocked for a missing one."""
    store = Store(repo)
    store.add_intent({"agent": "main", "intent": "edit login", "files": ["app/service.py"], "commands": [],
                      "verdict": "approved", "why": ""})
    asked = []
    monkeypatch.setattr(jev, "ask", fake_low_risk(asked))
    absolute = str(repo / "app" / "service.py")
    code, _, err = step.pre_tool({"tool": "apply_diff", "cwd": str(repo), "input": {"path": absolute, "diff": "x"}},
                                 store)
    assert code == 0, err
    assert "matches_intent" in asked[-1]
    EV.record({"tool": "apply_diff", "cwd": str(repo), "input": {"path": absolute, "diff": "x"}}, store)
    assert store.evidence()[-1]["file"] == "app/service.py"  # receipts match claims against this name


def test_stop_backstop_leaves_verified_work_alone(repo, monkeypatch):
    """Bob's last message reaches the Stop hook (probe, Sept 27). Judging a recap of verified work again put
    NEEDS EVIDENCE over VERIFIED (preflight, Sept 27); edits no accepted submission covers are still judged."""
    store = Store(repo)
    monkeypatch.setattr(jev, "ask", never)
    judged = []
    monkeypatch.setattr(receipts, "verify", lambda s, text, **k: judged.append(k.get("source")) or {"status": "accept"})
    s = store.session()
    s["edit_seq"], s["verified_edit_seq"] = 2, 2
    store.save_session(s)
    assert receipts.stop_hook(store, "Done: added the docstring, and 2 tests passed.") == (0, "", "")
    assert judged == []
    s = store.session()
    s["edit_seq"] = 3  # an edit after the verified submission
    store.save_session(s)
    receipts.stop_hook(store, "Done again.")
    assert judged == ["stop"]
