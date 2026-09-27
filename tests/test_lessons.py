"""Cross-session lessons (v4.2, L5 -> L0): a session's problems are summarized in code when it ends, and the
next SessionStart briefing opens with them. Jev is a fake."""
import json

import pytest

from conftest import FakeJev, make_repo, never
from hallmonitor import brief, hook, jev, lessons, mcp_server, report
from hallmonitor.store import Store

EVENTS = [
    {"stage": "session_start", "action": "brief"},
    {"stage": "intent", "target": "app/auth.py", "action": "block", "verdict": "rejected", "pattern": "exception"},
    {"stage": "intent", "target": "pip install redis", "action": "block", "verdict": "rejected",
     "pattern": "priority_inversion"},
    {"stage": "intent", "target": "app/service.py", "action": "allow", "verdict": "approved", "pattern": None},
    {"stage": "step", "tool": "write_file", "target": ".hallmonitor/config.json", "action": "block",
     "note": "protected: Hall Monitor's own configuration and records"},
    {"stage": "receipts", "action": "send_back", "verdicts": {"a": "verified", "b": "contradicted", "c": "needs_evidence",
                                                             "d": "contradicted"},
     "codes": {"b": "diff_mismatch", "c": "stale"}},
    {"stage": "receipts", "action": "send_back", "verdicts": {"c": "needs_evidence"}, "codes": {"c": "stale"}},
    {"stage": "receipts", "action": "accept", "verdicts": {"a": "verified"}, "codes": {}},
    {"stage": "stall", "action": "flag", "pattern": "looping on one failure"},
]


def test_summarize_names_excuses_reasons_stalls_and_protected_blocks():
    assert lessons.summarize(EVENTS) == [
        "Excuses rejected: exception (app/auth.py), priority inversion (pip install redis)",
        "Claims sent back: stale x2, diff_mismatch, judged contradicted",
        "Stalls: looping on one failure; blocked edits to Hall Monitor's files: .hallmonitor/config.json"]
    assert lessons.summarize([{"stage": "intent", "action": "allow", "verdict": "approved"}]) == []


@pytest.fixture
def repo(tmp_path):
    make_repo(tmp_path, {"app/auth.py": "def check():\n    return False\n"}, config={"test_command": "python -V"})
    return tmp_path


def test_a_fresh_repo_gets_no_lessons_line(repo, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    code, out, _ = hook.handle({"event": "SessionStart", "cwd": str(repo)})
    assert code == 0 and "From your last session" not in out
    assert not (repo / ".hallmonitor" / "lessons.json").exists()


def test_the_second_session_starts_with_the_first_sessions_lessons(repo, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    hook.handle({"hook_event_name": "SessionStart", "cwd": str(repo)})
    # Session 1: an excuse is rejected and an edit to Hall Monitor's own files is blocked.
    monkeypatch.setattr(jev, "ask", FakeJev(rationalization=("exception", 0.97), violates=0.9, on_task=0))
    verdict = mcp_server.call("declare_intent", {"intent": "Just this once, make check() return True.",
                                                 "files": ["app/auth.py"]}, Store(repo))
    assert "REJECTED" in verdict
    code, _, _ = hook.handle({"hook_event_name": "PreToolUse", "cwd": str(repo), "tool_name": "write_file",
                              "tool_input": {"path": str(repo / ".hallmonitor" / "config.json"), "content": "{}"}})
    assert code == 2
    hook.handle({"hook_event_name": "Stop", "cwd": str(repo), "last_assistant_message": "I could not finish."})
    saved = json.loads((repo / ".hallmonitor" / "lessons.json").read_text(encoding="utf-8"))
    assert saved["lines"][0] == "Excuses rejected: exception (app/auth.py)"
    # Session 2 opens with them.
    monkeypatch.setattr(jev, "ask", never)
    code, out, _ = hook.handle({"hook_event_name": "SessionStart", "cwd": str(repo)})
    assert code == 0
    assert "From your last session:\n- Excuses rejected: exception (app/auth.py)\n" in out
    assert "- Blocked edits to Hall Monitor's files: .hallmonitor/config.json" in out
    assert out.rstrip().endswith("sabotage probes.")  # the protocol line is still there
    # A third session after an empty second one still gets the most recent lessons.
    code, out, _ = hook.handle({"hook_event_name": "SessionStart", "cwd": str(repo)})
    assert "From your last session:" in out


def test_lessons_stay_within_max_brief_chars(repo, monkeypatch):
    monkeypatch.setattr(jev, "ask", never)
    store = Store(repo)
    for e in EVENTS[1:]:
        store.log(e)
    full = brief.session_start({}, store)[1]
    assert "From your last session:" in full and len(full) <= 1500
    for e in EVENTS[1:]:
        store.log(e)
    (store.dir / "config.json").write_text(json.dumps({"test_command": "python -V", "max_brief_chars": 620}))
    tight = brief.session_start({}, store)[1]
    assert len(tight) <= 620 and tight.rstrip().endswith("sabotage probes.")  # lessons dropped, protocol kept
    assert "From your last session:" in tight and tight.count("\n- ") < full.count("\n- ")  # only what fits


def test_the_hall_pass_shows_what_the_next_session_will_hear(repo):
    store = Store(repo)
    for e in EVENTS:
        store.log(e)
    report.write_hall_pass(store)
    page = (store.dir / "hall-pass.html").read_text(encoding="utf-8")
    assert "For the next session" in page and "Claims sent back: stale x2" in page
