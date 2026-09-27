"""v4 T1: when Jev can't answer, Hall Monitor falls back to code-only rules. Before, only HTTP 403 did: a
missing, wrong or expired key (401) and outages were retried and re-raised, and the hooks' catch-all let every
edit through unchecked (fail_open). Found by calling Jev with a wrong key, Sept 27."""
import httpx2
import pytest
from typesafe_sdk import TypeSafeAuthenticationError, TypeSafeError

from conftest import make_repo
from hallmonitor import hook, jev


class Client:
    def __init__(self, error):
        self.error, self.calls = error, 0

    def system_one(self, **kw):
        self.calls += 1
        raise self.error


@pytest.mark.parametrize("error", [TypeSafeError("No API key was provided."),
                                   TypeSafeAuthenticationError(401, None, httpx2.Headers(), "Cannot authenticate")])
def test_a_key_problem_is_a_refusal_at_once(monkeypatch, error):
    client = Client(error)
    monkeypatch.setattr(jev, "_get", lambda: client)
    monkeypatch.setattr(jev.time, "sleep", lambda s: pytest.fail("a key problem must not be retried"))
    with pytest.raises(jev.JevRefused, match="key"):
        jev.ask({}, {})
    assert client.calls == 1


def test_an_outage_is_a_refusal_after_the_retries(monkeypatch):
    client = Client(ConnectionError("network down"))
    monkeypatch.setattr(jev, "_get", lambda: client)
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    with pytest.raises(jev.JevRefused, match="unavailable"):
        jev.ask({}, {}, retries=3)
    assert client.calls == 3


def test_with_no_working_key_an_undeclared_edit_waits_for_the_user(tmp_path, monkeypatch):
    store = make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n"},
                      config={"test_command": "python -m pytest -q"})
    monkeypatch.setattr(jev, "_get", lambda: Client(TypeSafeError("No API key was provided.")))
    code, _, err = hook.handle({"event": "PreToolUse", "tool": "write_file", "cwd": str(store.root),
                                "input": {"path": "app/service.py", "content": "def login():\n    return 'x'\n"}})
    assert code == 2  # fail-closed: never waved through unchecked
    assert not [e for e in store.events() if e.get("stage") == "error" and "trace" in e]
