"""Deep review (v4.2, F3), behind config deep_review: off by default; when on and every claim verifies, the
riskiest files (at most 3) are reviewed by explore subagents before the round is accepted. Jev is a fake."""
import json

import pytest

from conftest import PASSING, FakeJev, make_repo
from hallmonitor import evidence as EV, jev, mcp_server, receipts, report, review
from hallmonitor.store import Store

FILES = {"app/auth.py": "def check():\n    return True\n", "app/service.py": "def login():\n    return 'ok'\n",
         "app/a.py": "A = 1\n", "app/b.py": "B = 1\n"}


@pytest.fixture
def store(tmp_path):
    store = make_repo(tmp_path, {"README.md": "x\n"},
                      config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
        EV.record({"tool": "write_file", "input": {"path": path, "content": text}}, store)
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"}, "output": "4 passed"}, store)
    return store


RISK = {"app/auth.py": 3.0, "app/service.py": 2.6, "app/a.py": 2.3, "app/b.py": 1.0}
CLAIMS = [{"claim": "All tests pass.", "evidence": ["E5"]}]


def fake(**extra):
    return FakeJev(risk=lambda qid, state: RISK[state["change"]["file"]], **extra)


def submit(store, **args):
    return mcp_server.call("submit_claims", {"claims": CLAIMS, **args}, store)


def turn_on(store):
    (store.dir / "config.json").write_text(json.dumps({**json.loads((store.dir / "config.json").read_text()),
                                                      "deep_review": True}))


def test_off_by_default_the_result_and_message_are_unchanged(store, monkeypatch):
    monkeypatch.setattr(jev, "ask", fake())
    result = receipts.verify(store, CLAIMS)
    assert review.after_verify(store, result, {"app/auth.py": "fine"}) is result
    assert review.message(result) == receipts.message(result)
    assert "REVIEW" not in submit(store)


def test_on_the_riskiest_files_are_reviewed_before_the_round_is_accepted(store, monkeypatch):
    turn_on(store)
    monkeypatch.setattr(jev, "ask", fake(defect=lambda qid, state: 0.9 if state["file"] == "app/auth.py" else 0.05))
    text = submit(store)
    assert "Deep review is on" in text
    assert [line.split()[3].rstrip(":") for line in text.splitlines() if line.startswith("REVIEW NEEDED")] == \
        ["app/auth.py", "app/service.py", "app/a.py"]  # highest risk first; app/b.py is below 2.2
    assert "do not edit anything" in text
    assert json.loads((store.dir / "receipts.json").read_text())["status"] == "review"
    notes = {"app/auth.py": "app/auth.py:2 check() always returns True, so any password is accepted.",
             "app/service.py": "No defects found.", str(store.root / "app" / "a.py"): "No defects found."}
    text = submit(store, review_notes=notes)  # absolute paths are matched repo-relative
    assert "Receipts: all 1 claims verified." in text
    assert "Deep review reports possible defects. Tell the user before you finish: app/auth.py:" in text
    saved = json.loads((store.dir / "receipts.json").read_text())
    assert saved["status"] == "accept" and [r["file"] for r in saved["review"]] == ["app/auth.py", "app/service.py", "app/a.py"]
    assert "## Deep review" in (store.dir / "receipts.md").read_text(encoding="utf-8")
    events = [e for e in Store(store.root).events() if e["stage"] == "review"]
    assert [e["action"] for e in events] == ["review", "flag"] and events[-1]["flagged"] == ["app/auth.py"]
    report.write_hall_pass(Store(store.root))
    page = (store.dir / "hall-pass.html").read_text(encoding="utf-8")
    assert "possible defect" in page and "always returns True" in page


def test_partial_notes_keep_the_review_open_and_clean_reviews_say_so(store, monkeypatch):
    turn_on(store)
    monkeypatch.setattr(jev, "ask", fake(defect=0.05))
    text = submit(store, review_notes={"app/auth.py": "No defects found."})
    assert "REVIEW NEEDED for app/service.py" in text and "REVIEW NEEDED for app/auth.py" not in text
    notes = {f: "No defects found." for f in ("app/auth.py", "app/service.py", "app/a.py")}
    assert "Deep review of app/auth.py, app/service.py, app/a.py: no defects reported." in submit(store, review_notes=notes)


def test_malformed_review_notes_just_leave_the_review_open(store, monkeypatch):
    turn_on(store)
    monkeypatch.setattr(jev, "ask", fake())
    text = submit(store, review_notes=["app/auth.py looks fine"])  # a list, not {file: findings}
    assert "REVIEW NEEDED for app/auth.py" in text


def test_no_review_unless_every_claim_verifies(store, monkeypatch):
    turn_on(store)
    monkeypatch.setattr(jev, "ask", fake())
    text = mcp_server.call("submit_claims", {"claims": [{"claim": "All tests pass.", "evidence": ["E99"]}]}, store)
    assert "REVIEW NEEDED" not in text and "[CONTRADICTED, unknown]" in text
