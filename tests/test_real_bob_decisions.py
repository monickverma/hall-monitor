"""Real Bob Shell run, Sept 27: `/decisions docs/security-policy.pdf` recorded D1-D6 correctly, then Receipts
contradicted Bob's claim that it had (the claim names the policy and app/auth.py, which didn't change) and
asked it to prove obligations about changes in a turn that changed nothing, until the cost cap. Jev is a fake."""
from conftest import PASSING, FakeJev, make_repo
from hallmonitor import jev, receipts

POLICY = "docs/security-policy.pdf"
BOB = ("Extracted all enforceable rules from docs/security-policy.pdf and recorded them as Hall Monitor decisions "
       "D1–D6 (constant-time passwords, security review for app/auth.py, stdlib-only dependencies).")


def repo(tmp_path):
    store = make_repo(tmp_path, {"app/auth.py": "def check():\n    return False\n", POLICY: "%PDF-1.4\n"},
                      config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})
    for i, (text, kind) in enumerate([("Changes to app/auth.py require a security review.", "obligation"),
                                      ("Password comparison must remain constant-time.", "limit"),
                                      ("Use only the Python standard library.", "limit"),
                                      ("New dependencies need written approval.", "obligation"),
                                      ("Every behavior change ships with a failing-first test.", "obligation"),
                                      ("Tests assert on the changed behavior.", "obligation")], 2):
        store.add_decision(text, f"{POLICY} §{i}", kind=kind)
    return store


def test_a_claim_about_recorded_rules_is_checked_against_the_rule_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    result = receipts.verify(store, [BOB])
    assert result["status"] == "accept"
    assert [(r["state"], r["code"]) for r in result["rows"]] == [("verified", "ledger")]  # no obligations: no edits
    wrong = receipts.verify(store, [BOB.replace("D1–D6", "D1–D7")])
    assert (wrong["rows"][0]["state"], wrong["rows"][0]["code"]) == ("contradicted", "unknown")
    assert "D7 is not in the rule ledger" in wrong["rows"][0]["detail"]
    assert receipts.recorded_decisions("The finished work satisfies rule D3.", {"D3"}) is None  # about the work


def test_a_claimed_change_that_never_happened_is_still_contradicted(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev())
    store = repo(tmp_path)
    result = receipts.verify(store, [{"claim": "Fixed the password check in app/auth.py.", "evidence": []}])
    assert (result["rows"][0]["state"], result["rows"][0]["code"]) == ("contradicted", "diff_mismatch")
