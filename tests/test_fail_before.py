"""Fail-before/pass-after (v4 design): Bob's changed tests, run against the code as it was before the change."""
import subprocess
import sys

from hallmonitor import gitutil
from conftest import make_repo

CMD = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'
BEFORE = "def limit():\n    return 0\n"
AFTER = "def limit():\n    return 5\n"


def change(tmp_path, test_body):
    store = make_repo(tmp_path, {"app/__init__.py": "", "app/rl.py": BEFORE, "tests/__init__.py": ""},
                      config={"test_command": CMD})
    (store.root / "app/rl.py").write_text(AFTER, encoding="utf-8")
    (store.root / "tests/test_rl.py").write_text(test_body, encoding="utf-8")
    base = store.session()["base"]
    return store, base, gitutil.changes(store.root, base)


def test_a_test_that_checks_the_change_fails_on_the_old_code(tmp_path):
    store, base, ch = change(tmp_path, "from app.rl import limit\n\ndef test_limit():\n    assert limit() == 5\n")
    fb = gitutil.fail_before(store.root, base, ch, CMD)
    assert fb["on_code_before_change"] == "fail" and fb["changed_tests"] == ["tests/test_rl.py"]
    assert (store.root / "app/rl.py").read_text() == AFTER  # the working tree is never touched
    assert "passed" in subprocess.run(CMD, cwd=store.root, shell=True, capture_output=True, text=True).stdout


def test_a_vacuous_test_passes_on_the_old_code(tmp_path):
    store, base, ch = change(tmp_path, "from app.rl import limit\n\ndef test_limit():\n    assert limit() is not None\n")
    assert gitutil.fail_before(store.root, base, ch, CMD)["on_code_before_change"] == "pass"
    assert gitutil.fail_before(store.root, base, {"app/rl.py": ch["app/rl.py"]}, CMD) is None  # no changed tests
