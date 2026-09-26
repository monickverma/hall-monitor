"""Thin Jev wrapper: one request per decision point, retries, token accounting.

The model is pinned: `jev-latest` moves, and every threshold here was tuned against one model.
Jev bills input tokens only (output is free, docs.typesafe.ai/models), so `tokens()` counts input tokens.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from typesafe_sdk import TypeSafeClient, TypeSafePermissionDeniedError

MODEL = os.environ.get("HM_JEV_MODEL", "jev-1.13.0")
PRICE_PER_M_INPUT = 0.042  # $ per 1M input tokens; output tokens are free (docs.typesafe.ai/models)

_client = None


class JevRefused(Exception):
    """Jev answered HTTP 403 (a content block, or a key problem). Callers fall back to code-only rules."""


def _get():
    global _client
    if _client is None:
        _client = TypeSafeClient(model=MODEL)
    return _client


def ask(state, questions, retries=3):
    """Ask every question over one state in a single parallel request.

    Returns (answers, usage) as plain dicts: answers[id] has `noul`, or `choice`/`probabilities`/
    `confidence`, or `score`/`probabilities`/`confidence`. usage has the token counts and the model id.
    """
    for attempt in range(retries):
        try:
            r = _get().system_one(state=state, questions=questions).model_dump()
            return r["answers"], {**r["usage"], "model": r.get("model") or MODEL}
        except TypeSafePermissionDeniedError as e:
            raise JevRefused(str(e)) from e  # retrying a content block only repeats it
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
    """Billable tokens: Jev bills input tokens only."""
    return usage["input_tokens"]


def cost(n_tokens):
    return n_tokens * PRICE_PER_M_INPUT / 1e6
