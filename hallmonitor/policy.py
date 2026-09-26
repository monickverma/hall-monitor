"""Decision engine: Jev supplies beliefs, this module supplies values.

A greedy decision tree (take the argmax at every node, then descend) multiplies errors and
throws away uncertainty: three 90%-sure hops are only 73% sure, and the tree never learns that
a small chance of a catastrophic outcome should outweigh a large chance of a harmless one.

Instead, every judgment for an event is asked at once (Jev speculative fan-out), turned into a
distribution over joint "worlds", and the action with the minimum expected loss is chosen.
That is the globally best action for the given beliefs and harm table.

Escalation uses the expected value of partial information (EVPPI): Jev's confident answers are
taken as settled, and a closer look is bought only when resolving the uncertain ones could
lower the expected loss by more than the look costs.
"""
from dataclasses import dataclass, field
from itertools import product

# Harm of taking an action when a risk is present ("ok" = no risk present). Risks add up.
# Conflict detection between agents is low-precision (the SID paper reports 27.9%), so a likely
# conflict is answered with a note naming the other agent's work; only a near-certain one blocks.
STEP_HARM = {
    "allow":   {"ok": 0,  "destructive": 100, "violates": 30, "off_task": 8, "rationalizing": 15,
                "conflict": 12, "mismatch": 25},
    "rebrief": {"ok": 3,  "destructive": 100, "violates": 27, "off_task": 2, "rationalizing": 10,
                "conflict": 4, "mismatch": 22},
    "block":   {"ok": 15, "destructive": 0,   "violates": 0,  "off_task": 4, "rationalizing": 0,
                "conflict": 0, "mismatch": 0},
}
CLAIM_HARM = {
    "accept":    {"ok": 0, "unsupported": 8, "contradicted": 30},
    "flag":      {"ok": 3, "unsupported": 2, "contradicted": 12},
    "send_back": {"ok": 6, "unsupported": 1, "contradicted": 0},
}
PLAN_HARM = {
    "allow": {"ok": 0,  "violates": 30, "uncertified": 6},
    "block": {"ok": 8,  "violates": 0,  "uncertified": 0},
}


@dataclass
class Decision:
    action: str
    expected_loss: dict
    evppi: float
    escalate: bool = False
    risks: dict = field(default_factory=dict)

    def as_dict(self):
        return {"action": self.action, "evppi": round(self.evppi, 3), "escalate": self.escalate,
                "expected_loss": {a: round(v, 3) for a, v in self.expected_loss.items()},
                "risks": {k: round(v, 3) for k, v in self.risks.items()}}


def independent(risks, band=(0.1, 0.9)):
    """Worlds for independent yes/no risks. Risks inside `band` count as unresolved."""
    names = list(risks)
    worlds = []
    for bits in product((0, 1), repeat=len(names)):
        p = 1.0
        for n, b in zip(names, bits):
            p *= risks[n] if b else 1 - risks[n]
        worlds.append((p, frozenset(n for n, b in zip(names, bits) if b)))
    unresolved = frozenset(n for n, p in risks.items() if band[0] <= p <= band[1])
    return worlds, (lambda w: w & unresolved)


def exclusive(dist, ok_label, confident=0.9):
    """Worlds for one mutually exclusive label (a Choice). Unresolved unless one label dominates."""
    worlds = [(p, frozenset() if label == ok_label else frozenset([label])) for label, p in dist.items()]
    unresolved = max(dist.values()) < confident
    return worlds, ((lambda w: w) if unresolved else (lambda w: None))


def decide(worlds, reveal, harm, escalate_cost=None, risks=None):
    def loss(action, present):
        h = harm[action]
        return sum(h.get(k, 0) for k in present) if present else h["ok"]

    el = {a: sum(p * loss(a, w) for p, w in worlds) for a in harm}
    best = min(el, key=el.get)
    groups = {}
    for p, w in worlds:
        groups.setdefault(reveal(w), []).append((p, w))
    after = sum(min(sum(p * loss(a, w) for p, w in g) for a in harm) for g in groups.values())
    evppi = max(0.0, el[best] - after)
    return Decision(best, el, evppi, escalate_cost is not None and evppi > escalate_cost, risks or {})


def noisy_or(ps):
    q = 1.0
    for p in ps:
        q *= 1 - p
    return 1 - q
