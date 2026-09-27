"""Receipts over several rounds: the free uncited retry, a stale test run re-run to verified, STUCK after
two send-backs, and an audit resubmission that finishes the same round. Jev is a fake."""
import pytest

from conftest import PASSING, FakeJev, make_repo
from hallmonitor import evidence as EV, jev, receipts
from hallmonitor.store import Store

LIMITER = "Implemented the limiter in app/ratelimit.py."


@pytest.fixture
def store(tmp_path):
    return make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n"},
                     config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})


def edit(store, path, text):
    (store.root / path).parent.mkdir(parents=True, exist_ok=True)
    (store.root / path).write_text(text, encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": path, "content": text}}, store)
    return store.evidence()[-1]["id"]


def run_tests(store, output="1 passed in 0.01s"):
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"}, "output": output}, store)
    return [r for r in store.evidence() if r["kind"] == "test"][-1]["id"]



def test_uncited_claims_get_one_free_retry_then_are_judged_and_marked(store, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    edit(store, "app/ratelimit.py", "LIMIT = 5\n")
    run_tests(store)
    first = receipts.verify(store, [LIMITER])  # plain text, no receipts cited
    assert first["status"] == "needs_evidence" and first["send_backs"] == 0
    assert (first["rows"][0]["state"], first["rows"][0]["code"], first["rows"][0]["tier"]) == \
        ("needs_evidence", "uncited", "code")
    assert "doesn't count as a send-back" in receipts.message(first)
    second = receipts.verify(store, [LIMITER])  # the retry is spent: judged the old way, marked uncited
    row = second["rows"][0]
    assert (row["state"], row["code"], row["tier"]) == ("verified", "uncited", "jev")
    assert second["status"] == "accept" and second["send_backs"] == 0


def test_a_stale_test_run_is_sent_back_then_a_fresh_run_verifies(store, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    edit(store, "app/ratelimit.py", "LIMIT = 5\n")
    old = run_tests(store)
    edit(store, "app/ratelimit.py", "LIMIT = 6\n")  # a code edit after the test run
    first = receipts.verify(store, [{"claim": "All tests pass.", "evidence": [old]}])
    row = first["rows"][0]
    assert (row["state"], row["code"]) == ("needs_evidence", "stale") and first["status"] == "send_back"
    assert f"{old} ran before your last code edit" in row["detail"] and first["send_backs"] == 1
    fresh = run_tests(store)
    second = receipts.verify(store, [{"claim": "All tests pass.", "evidence": [fresh]}])
    assert second["rows"][0]["state"] == "verified" and second["status"] == "accept"
    assert second["send_backs"] == 0  # a verified round resets the count
    assert Store(store.root).session()["verified_edit_seq"] == 2


def test_the_third_send_back_is_stuck_and_names_the_checkpoint(store, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    edit(store, "app/ratelimit.py", "LIMIT = 5\n")
    run_tests(store)  # a passing run: checkpoint C1
    claims = [{"claim": LIMITER, "evidence": ["E99"]}]  # cites a receipt that doesn't exist
    results = [receipts.verify(store, claims) for _ in range(3)]
    assert [r["status"] for r in results] == ["send_back", "send_back", "stuck"]
    assert [r["send_backs"] for r in results] == [1, 2, 3]
    assert results[0]["rows"][0]["code"] == "unknown"
    msg = receipts.message(results[-1])
    assert "STUCK" in msg and "refs/hallmonitor/C1" in msg and "never rolls back by itself" in msg
    stalls = [e for e in Store(store.root).events() if e["stage"] == "stall"]
    assert [e["pattern"] for e in stalls] == ["repeating a rejected approach"] * 2  # rounds 2 and 3


def test_an_audit_resubmission_finishes_the_same_round(store, monkeypatch):
    edit_id = edit(store, "app/ratelimit.py", "LIMIT = 5\n")
    run_id = run_tests(store)
    claims = [{"claim": LIMITER, "evidence": [edit_id, run_id]}]
    s = store.session()
    s["send_backs"] = 1  # one ordinary send-back already
    store.save_session(s)
    # The verdict says "contradicts" but the separate "shows false" reading disagrees, at every tier: audit.
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("contradicts", 0.95), false=0.1))
    first = receipts.verify(store, claims)
    assert first["status"] == "audit" and [a["index"] for a in first["audits"]] == [0]
    assert first["rows"][0]["state"] == "cant_check" and first["send_backs"] == 1
    assert "AUDIT NEEDED for claim 0" in receipts.message(first)
    # With the requested audit attached, both readings agree the claim is false.
    monkeypatch.setattr(jev, "ask", FakeJev(verdict=("contradicts", 0.95), false=0.95))
    second = receipts.verify(store, claims, audit_notes={"0": "app/ratelimit.py only sets LIMIT = 5."})
    assert second["rows"][0]["tier"] == "jev+audit" and second["status"] == "send_back"
    assert second["send_backs"] == 1  # the audited round is the same round, not a new send-back
    third = receipts.verify(store, claims)  # a new submission is a new round
    assert third["send_backs"] == 2
