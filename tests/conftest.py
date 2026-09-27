"""Shared test setup. Unit tests never reach the real Jev: CI has no key, and a test that calls Jev by
accident should fail loudly rather than spend money or pass by luck. Tests that need answers replace
jev.ask with a fake (FakeJev below, or the small fakes in test_review_fixes.py)."""
import subprocess

import pytest

from hallmonitor import bob, jev, receipts
from hallmonitor.store import Store


class RealJevCall(BaseException):
    """A unit test reached the real Jev client. It derives from BaseException so that neither the retry
    loop in jev.ask nor Hall Monitor's fail-open handlers (`except Exception`) can swallow it."""


@pytest.fixture(autouse=True)
def no_real_jev(monkeypatch):
    def real_client():
        raise RealJevCall("a unit test tried to call the real Jev; replace jev.ask with a fake")
    monkeypatch.setattr(jev, "_client", None)
    monkeypatch.setattr(jev, "_get", real_client)
    # Never start Bob Shell from a test either: `bob run` spends Bobcoins.
    monkeypatch.setenv("HM_DISABLE_BOB_SHELL", "1")
    monkeypatch.setattr(bob, "_run", lambda *a, **k: None)


# ---------------------------------------------------------------- a fake Jev that answers any question

GOOD_NOUL = {"matches_intent", "handles_failure"}   # questions where a high p is the benign answer
SCORE_DEFAULT = {"on_task": 3, "serves": 3, "risk": 1}


class FakeJev:
    """Stands in for jev.ask. Every question gets a benign answer of the right shape (Noul, Choice or
    Score) unless an override names it: FakeJev(verdict=("contradicts", 0.95), false=0.9, s0_D1=0.97).
    An override key matches a question id exactly or as a prefix before "_" (the longest match wins);
    a value may be a function of (question id, state). Claim kinds default to receipts.kind_by_code."""

    def __init__(self, **overrides):
        self.overrides = overrides
        self.calls = []

    def __call__(self, state, questions):
        self.calls.append({"state": state, "questions": set(questions)})
        answers = {qid: self.answer(qid, q, state) for qid, q in questions.items()}
        return answers, {"input_tokens": 10, "output_tokens": 0, "model": "fake"}

    def value(self, qid, state):
        keys = [k for k in self.overrides if qid == k or qid.startswith(k + "_")]
        if not keys:
            return None
        v = self.overrides[max(keys, key=len)]
        return v(qid, state) if callable(v) else v

    def answer(self, qid, q, state):
        v = self.value(qid, state)
        kind = type(q).__name__
        if kind == "Noul":
            return {"noul": (0.97 if qid in GOOD_NOUL else 0.03) if v is None else v}
        if kind == "Choice":
            labels = list(q.criteria)
            if v is None:
                v = receipts.kind_by_code(state["sentences"][int(qid.split("_")[1])]) \
                    if qid.startswith("kind_") else (labels[0], 0.97)
            label, p = v if isinstance(v, tuple) else (v, 0.97)
            rest = (1 - p) / (len(labels) - 1)
            return {"choice": label, "confidence": p,
                    "probabilities": {x: (p if x == label else rest) for x in labels}}
        levels = len(q.criteria)
        s = SCORE_DEFAULT.get(qid, 0) if v is None else v
        return {"score": float(s), "confidence": 1.0,
                "probabilities": {str(i): (1.0 if i == round(s) else 0.0) for i in range(levels)}}


def never(*a, **k):
    raise AssertionError("Jev must not be asked")


# ---------------------------------------------------------------- a small git repository

def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false",
                    *args], cwd=root, check=True, capture_output=True)


PASSING = "python -c \"print('1 passed')\""


def make_repo(root, files, config=None):
    """Commit `files` as the base of a session and return its Store (config.json written if given)."""
    for path, text in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    store = Store(root)
    if config is not None:
        import json
        (store.dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    s = store.session()
    s["base"] = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                               text=True).stdout.strip()
    store.save_session(s)
    return store
