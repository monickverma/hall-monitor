"""Shared test setup. Unit tests never reach the real Jev: CI has no key, and a test that calls Jev by
accident should fail loudly rather than spend money or pass by luck. Tests that need answers replace
jev.ask with a fake (see test_review_fixes.py)."""
import pytest

from hallmonitor import jev


class RealJevCall(BaseException):
    """A unit test reached the real Jev client. It derives from BaseException so that neither the retry
    loop in jev.ask nor Hall Monitor's fail-open handlers (`except Exception`) can swallow it."""


@pytest.fixture(autouse=True)
def no_real_jev(monkeypatch):
    def real_client():
        raise RealJevCall("a unit test tried to call the real Jev; replace jev.ask with a fake")
    monkeypatch.setattr(jev, "_client", None)
    monkeypatch.setattr(jev, "_get", real_client)
