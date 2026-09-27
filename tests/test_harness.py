"""The test harness itself: a unit test that reaches the real Jev fails at once, whatever catches it."""
import pytest

from conftest import RealJevCall
from hallmonitor import jev


def test_a_real_jev_call_fails_fast():
    with pytest.raises(RealJevCall):
        jev.ask({"x": 1}, {"q": None})  # no retries, no sleep: RealJevCall is not an Exception


def test_fail_open_cannot_hide_a_real_jev_call(tmp_path):
    from hallmonitor import hook
    (tmp_path / "AGENTS.md").write_text("## Decisions\n- Never touch app/auth.py.\n")  # SessionStart asks Jev
    with pytest.raises(RealJevCall):
        hook.handle({"event": "SessionStart", "cwd": str(tmp_path)})
