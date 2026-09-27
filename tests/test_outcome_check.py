"""v4 T2: a failed command must be dealt with in the next declared intent (the outcome check), and every
event carries the model and a hash of the question wording (T1). Jev is a fake."""
from conftest import FakeJev, make_repo
from hallmonitor import evidence as EV, jev, step
from hallmonitor.store import Store


def failed(tmp_path):
    store = make_repo(tmp_path, {"app/service.py": "def login():\n    return 'ok'\n"},
                      config={"test_command": "python -m pytest -q"})
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"},
               "output": "FAILED tests/test_service.py::test_login\n1 failed, 2 passed in 0.02s"}, store)
    assert Store(store.root).session()["failed_step"]["command"] == "python -m pytest -q"
    return store


def test_an_intent_that_ignores_the_failed_step_is_approved_only_with_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(handles_failure=0.1))
    store = failed(tmp_path)
    msg = step.declare_intent(store, "Add a docstring to login()", files=["app/service.py"])
    assert "deal with the failed step first" in msg and "python -m pytest -q" in msg
    assert Store(store.root).session()["failed_step"] is not None  # still pending


def test_an_intent_that_deals_with_it_clears_it(tmp_path, monkeypatch):
    monkeypatch.setattr(jev, "ask", FakeJev(handles_failure=0.9))
    store = failed(tmp_path)
    msg = step.declare_intent(store, "Fix login() so test_login passes", files=["app/service.py"])
    assert "approved" in msg and "failed step" not in msg
    assert Store(store.root).session()["failed_step"] is None
    intent = [e for e in store.events() if e["stage"] == "intent"][-1]
    assert intent["handles_failure"] == 0.9 and intent["model"] and intent["qhash"]  # T1: model and wording hash
