"""Thin Jev wrapper: one request per decision point, retries, token accounting."""
import time
from concurrent.futures import ThreadPoolExecutor

from typesafe_sdk import TypeSafeClient

_client = None


def _get():
    global _client
    if _client is None:
        _client = TypeSafeClient()
    return _client


def ask(state, questions, retries=3):
    """Ask every question over one state in a single parallel request.

    Returns (answers, usage) as plain dicts: answers[id] has `noul`, or `choice`/`probabilities`/
    `confidence`, or `score`/`probabilities`/`confidence`.
    """
    for attempt in range(retries):
        try:
            r = _get().system_one(state=state, questions=questions).model_dump()
            return r["answers"], r["usage"]
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(1.5 * 2 ** attempt)


def ask_many(jobs, workers=8):
    """Run independent (state, questions) requests concurrently, preserving order."""
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda j: ask(*j), jobs))


def p_levels(answer, levels):
    """Probability mass a Score answer puts on the given levels."""
    probs = {int(k): v for k, v in answer["probabilities"].items()}
    return sum(probs.get(l, 0.0) for l in levels)


def tokens(usage):
    return usage["input_tokens"] + usage["output_tokens"]
