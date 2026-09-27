"""Cycle-rate stall signal (v4.2): the same 2-3 steps over and over, with the same content and the same
outcomes, count a stall named "going in circles". No Jev calls."""
import pytest

from conftest import make_repo
from hallmonitor import evidence as EV


@pytest.mark.parametrize("keys,unit", [
    (list("abab"), None),                   # too short
    (list("ababab"), list("ab")),
    (list("xabcabc"), list("abc")),
    (list("aaaaaa"), None),                 # one step repeated: the older stall patterns cover it
    (list("ababac"), None),
    (list("abcabd"), None),
])
def test_repeating_unit(keys, unit):
    assert EV.repeating_unit(keys) == unit


@pytest.fixture
def store(tmp_path):
    return make_repo(tmp_path, {"app.py": "X = 1\n"}, config={"test_command": "python -m pytest -q"})


def edit(store, content):
    EV.record({"tool": "write_file", "input": {"path": "app.py", "content": content}}, store)


def run(store, command, output):
    EV.record({"tool": "execute_command", "input": {"command": command}, "output": output}, store)


def circles(store):
    return [e for e in store.events() if e.get("stage") == "stall" and e["pattern"] == "going in circles"]


def test_flip_flopping_between_two_versions_is_going_in_circles(store):
    for _ in range(3):
        edit(store, "X = 2\n")
        run(store, "python -m pytest -q", "1 failed in 0.01s")
    found = circles(store)
    assert len(found) == 1 and "repeat the same 2 steps (edit app.py -> `python -m pytest -q`)" in found[0]["target"]
    assert any("going in circles" in n for n in store.session()["notes"])


def test_an_edit_test_loop_that_makes_progress_is_not_a_circle(store):
    for i in range(4):
        edit(store, f"X = {i}\n")
        run(store, "python -m pytest -q", "1 failed in 0.01s" if i < 3 else "1 passed in 0.01s")
    assert circles(store) == []


def test_a_three_command_loop_with_the_same_failures(store):
    for _ in range(2):
        run(store, "pip install limiter", "ERROR: No matching distribution found for limiter")
        run(store, "python app.py", "Traceback (most recent call last):\nModuleNotFoundError: limiter")
        run(store, "python -m pytest -q", "1 failed in 0.01s")
    assert len(circles(store)) == 1
    assert store.session()["cycle"] == []  # counted once, then the window starts again
