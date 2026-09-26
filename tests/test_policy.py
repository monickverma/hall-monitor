from hallmonitor import policy


def test_worlds_are_a_distribution():
    worlds, _ = policy.independent({"a": 0.3, "b": 0.9, "c": 0.05})
    assert abs(sum(p for p, _ in worlds) - 1) < 1e-9


def test_global_beats_greedy_on_small_catastrophic_risk():
    # A greedy tree reads "destructive? 85% no" and allows. Expected loss says a 15% chance of an
    # irreversible action costs more than a wrongful block, so it blocks (or looks closer first).
    risks = {"destructive": 0.15, "violates": 0.02, "off_task": 0.05}
    worlds, reveal = policy.independent(risks)
    d = policy.decide(worlds, reveal, policy.STEP_HARM, escalate_cost=3.0, risks=risks)
    assert d.action == "block" or d.escalate


def test_confident_beliefs_do_not_escalate():
    risks = {"destructive": 0.01, "violates": 0.03, "off_task": 0.02}
    worlds, reveal = policy.independent(risks)
    d = policy.decide(worlds, reveal, policy.STEP_HARM, escalate_cost=3.0, risks=risks)
    assert d.action == "allow" and not d.escalate


def test_uncertain_violation_escalates():
    risks = {"destructive": 0.01, "violates": 0.4, "off_task": 0.05}
    worlds, reveal = policy.independent(risks)
    assert policy.decide(worlds, reveal, policy.STEP_HARM, escalate_cost=3.0, risks=risks).escalate


def test_claim_policy():
    worlds, reveal = policy.exclusive({"verified": 0.95, "unsupported": 0.04, "contradicted": 0.01}, "verified")
    assert policy.decide(worlds, reveal, policy.CLAIM_HARM).action == "accept"
    worlds, reveal = policy.exclusive({"verified": 0.1, "unsupported": 0.2, "contradicted": 0.7}, "verified")
    assert policy.decide(worlds, reveal, policy.CLAIM_HARM).action == "send_back"
