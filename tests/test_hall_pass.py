"""The Hall Pass renders from empty and full state, and everything that came from Bob or the user is
HTML-escaped. No Jev calls: the page is built from .hallmonitor/ only."""
import json
from pathlib import Path

from hallmonitor import report
from hallmonitor.store import Store

EVIL = '<script>alert("hm")</script>'


def render(store):
    path, summary = report.write_hall_pass(store)
    return Path(path).read_text(encoding="utf-8"), summary


def test_empty_state(tmp_path):
    page, summary = render(Store(tmp_path))
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert "IN PROGRESS" in page and "No goal recorded" in page and "No claims submitted yet" in page
    assert summary.startswith("0 actions/intents judged, 0 stopped")


def full_store(root):
    store = Store(root)
    s = store.session()
    s["goal"] = f"Add a limiter {EVIL}"
    store.save_session(s)
    store.add_decision(f"Never touch app/auth.py {EVIL}", "docs/security-policy.pdf §2")
    store.add_decision("Keep the counters in memory.", "user", supersedes="D1")
    store.log({"stage": "session_start", "action": "brief", "tokens": 0})
    store.log({"stage": "ledger", "action": "record", "text": EVIL, "source": "docs/security-policy.pdf §2"})
    store.log({"stage": "intent", "agent": f"subagent {EVIL}", "target": f"app/{EVIL}.py", "action": "block",
               "verdict": "rejected", "pattern": "exception", "violations": {"D1": 0.9},
               "risks": {"destructive": 0.8, "off_task": 0.9}, "escalated": "deep_look", "tokens": 120})
    store.log({"stage": "step", "tool": "write_file", "target": ".hallmonitor/config.json", "action": "block",
               "note": f"protected: {EVIL}"})
    store.log({"stage": "plan", "action": "block", "missing_sections": [EVIL], "tokens": 30})
    store.log({"stage": "stall", "action": "flag", "pattern": "looping on one failure", "target": EVIL})
    store.log({"stage": "receipts", "source": "mcp", "claims": 2, "action": "send_back", "send_backs": 1,
               "verdicts": {"a": "verified", "b": "contradicted"}, "tiers": ["code", "jev"], "mutants": 3,
               "survived": 1, "tokens": 400})
    store.log({"stage": "error", "error": f"KeyError {EVIL}"})  # errors are never shown on the page
    store.add_evidence({"kind": "edit", "file": "app/ratelimit.py", "tool": "write_file", "edit_seq": 1})
    store.add_evidence({"kind": "test", "command": "python -m pytest -q", "status": "pass", "edit_seq": 1,
                        "tail": "3 passed"})
    store.add_evidence({"kind": "checkpoint", "checkpoint": "C1", "ref": "refs/hallmonitor/C1", "commit": "abc",
                        "tree": "def", "from": "E2", "edit_seq": 1})
    rows = [{"index": 0, "claim": f"Implemented the limiter {EVIL}", "kind": "implemented", "cited": ["E1", "E2"],
             "named": [], "state": "verified", "code": None, "detail": "", "tier": "jev", "action": "accept"},
            {"index": 1, "claim": "Wired it into app/service.py.", "kind": "implemented", "cited": ["E2"],
             "named": ["app/service.py"], "state": "contradicted", "code": "diff_mismatch",
             "detail": f"None of the files this claim names ({EVIL}) changed.", "tier": "code",
             "action": "send_back"}]
    (store.dir / "receipts.json").write_text(json.dumps({
        "rows": rows, "status": "send_back", "send_backs": 1, "audits": [], "risky_files": [],
        "tests": {"command": "python -m pytest -q", "passed": True, "tail": ["3 passed"]},
        "sabotage": {"mutants": 3, "killed": 2, "survived": [{"file": "app/ratelimit.py", "line": 3, "from": "a",
                                                              "to": "b", "killed": False}]},
        "checkpoint": {"checkpoint": "C1", "ref": "refs/hallmonitor/C1", "from": "E2"}}), encoding="utf-8")
    (store.dir / "forms.json").write_text(json.dumps({"events": 9, "needs_person": 2,
                                                       "forms": {"premature_completion": 1}}))
    return store


def test_full_state_is_rendered_and_escaped(tmp_path):
    page, summary = render(full_store(tmp_path))
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "SENT BACK" in page  # the stamp follows the last receipts round
    assert "<s>Never touch app/auth.py &lt;script&gt;" in page  # D1 was superseded by D2
    assert "reason: diff_mismatch" in page and "cites E1, E2" in page
    assert "sabotage 2/3 mutants killed" in page and "git checkout refs/hallmonitor/C1 -- ." in page
    assert "Failure forms" in page and "premature completion" in page
    assert "exception" in page and "escalated: deep_look" in page
    assert "KeyError" not in page
    assert "Evidence ledger: 2 receipts, 1 checkpoints" in page
    assert summary.startswith("3 actions/intents judged, 3 stopped") and "receipts: SENT BACK" in summary


def test_stuck_state_shows_the_restore_advice(tmp_path):
    store = full_store(tmp_path)
    store.log({"stage": "receipts", "source": "mcp", "claims": 2, "action": "stuck", "send_backs": 3,
               "verdicts": {"b": "contradicted"}, "tiers": ["code"], "mutants": 0, "survived": 0})
    data = json.loads((store.dir / "receipts.json").read_text(encoding="utf-8"))
    data["status"] = "stuck"
    (store.dir / "receipts.json").write_text(json.dumps(data), encoding="utf-8")
    page, _ = render(store)
    assert "STUCK" in page and "<h2>Stuck</h2>" in page and "hm-before-restore" in page
