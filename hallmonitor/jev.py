"""Thin Jev wrapper: one request per decision point, retries, token accounting.

The model is pinned: `jev-latest` moves, and every threshold here was tuned against one model.
Jev bills input tokens only (output is free, docs.typesafe.ai/models), so `tokens()` counts input tokens.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from typesafe_sdk import TypeSafeAuthenticationError, TypeSafeClient, TypeSafeError, TypeSafePermissionDeniedError

CALIBRATED_MODEL = "jev-1.13.0"  # the harm weights, thresholds, control set and eval/ results were tuned on this
# HM_JEV_MODEL exists for re-calibrating a new model (run eval/control_set.py and eval/seeded.py with it).
# Any other model is marked as uncalibrated on every Hall Pass until its calibration is in place.
MODEL = os.environ.get("HM_JEV_MODEL", CALIBRATED_MODEL)
UNCALIBRATED = MODEL != CALIBRATED_MODEL
PRICE_PER_M_INPUT = 0.042  # $ per 1M input tokens; output tokens are free (docs.typesafe.ai/models)

_client = None


class JevRefused(Exception):
    """Jev can't answer: HTTP 403 (a content block), a missing, wrong or expired key (401), or an outage that
    outlasted the retries. Callers fall back to code-only rules."""


def _get():
    global _client
    if _client is None:
        _client = TypeSafeClient(model=MODEL)
    return _client


def load_key_from_user_env():
    """Bob starts the MCP server without the user's environment: in the probe (Sept 27), TYPESAFE_API_KEY
    set in the shell that ran `bob run` never reached it. On Windows, read the key from where `setx`
    saved it, so it still never goes in a file. Called by the entry scripts Bob launches, not by tests."""
    if os.environ.get("TYPESAFE_API_KEY", "").startswith("${"):  # Bob leaves ${env:NAME} as is when NAME is unset
        del os.environ["TYPESAFE_API_KEY"]
    if os.environ.get("TYPESAFE_API_KEY") or os.name != "nt":
        return
    import winreg
    for hive, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(hive, sub) as k:
                key = winreg.QueryValueEx(k, "TYPESAFE_API_KEY")[0]
        except OSError:
            continue
        if key:
            os.environ["TYPESAFE_API_KEY"] = key
            return


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
        except (TypeSafeAuthenticationError, TypeSafeError) as e:
            if type(e) in (TypeSafeAuthenticationError, TypeSafeError):  # a missing, wrong or expired key
                # Before, this was retried and then raised as-is: the hooks' catch-all let every edit through
                # unchecked (fail_open), so a key problem quietly switched supervision off.
                raise JevRefused(f"Jev can't be reached with this key: {e}") from e
            if attempt == retries - 1:
                raise JevRefused(f"Jev is unavailable: {e}") from e
            time.sleep(1.5 * 2 ** attempt)
        except Exception as e:
            if attempt == retries - 1:  # an outage: fall back to code-only rules, like a refusal
                raise JevRefused(f"Jev is unavailable: {e}") from e
            time.sleep(1.5 * 2 ** attempt)


def ask_many(jobs, workers=8, return_refusals=False):
    """Run independent (state, questions) requests concurrently, preserving order. With
    return_refusals, a refused request yields its JevRefused in place of a result, so one refusal
    doesn't sink the others."""
    def one(job):
        try:
            return ask(*job)
        except JevRefused as e:
            if return_refusals:
                return e
            raise
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, jobs))


def p_levels(answer, levels):
    """Probability mass a Score answer puts on the given levels."""
    probs = {int(k): v for k, v in answer["probabilities"].items()}
    return sum(probs.get(l, 0.0) for l in levels)


def tokens(usage):
    """Billable tokens: Jev bills input tokens only."""
    return usage["input_tokens"]


def cost(n_tokens):
    return n_tokens * PRICE_PER_M_INPUT / 1e6
