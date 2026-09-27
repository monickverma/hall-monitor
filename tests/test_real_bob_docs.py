"""Real Bob, Sept 27 (task B, docs): Receipts sent back a correct docs edit until STUCK. Bob grouped its
claims under file headers, and Jev was shown no docs diff at all. Jev is a fake."""
from conftest import PASSING, FakeJev, make_repo
from hallmonitor import evidence as EV, jev, receipts

# Bob's own final message, shortened (bob_sessions/2026-09-27_taskB-docs_member1.json)
BOB_SUMMARY = """## What was done

Both files were fully updated per the spec:

**[`README.md`](README.md)** — E1:
- Added "Install and first run" section pointing to `scripts/setup_demo.py` and `BOB_RUNBOOK.md`
- First line kept as `# Hall Monitor: code review of AI-written changes, for IBM Bob` ✓ (D3)

**[`ARCHITECTURE.md`](ARCHITECTURE.md)** — E2:
- Added "going in circles" to L2 stall patterns
"""


def test_list_items_carry_their_headers_files_and_receipts():
    parsed = receipts.parse(BOB_SUMMARY)
    texts = [t for t, _ in parsed]
    assert not any(t.endswith(":") or t.startswith("#") for t in texts)  # headers are not claims
    assert [ids for _, ids in parsed] == [["E1"], ["E1"], ["E2"]]
    assert texts[0].endswith("[from the header: README.md E1]")
    assert receipts.named_files(texts[0], ["README.md", "BOB_RUNBOOK.md", "scripts/setup_demo.py"]) == \
        ["BOB_RUNBOOK.md", "README.md", "scripts/setup_demo.py"]
    # a list that follows an ordinary sentence carries nothing
    assert receipts.parse("I fixed the login bug.\n- Added a test for it in tests/test_login.py") == \
        [("I fixed the login bug.", []), ("Added a test for it in tests/test_login.py", [])]


def test_a_claim_about_a_doc_is_judged_on_that_docs_diff(tmp_path, monkeypatch):
    fake = FakeJev()
    monkeypatch.setattr(jev, "ask", fake)
    store = make_repo(tmp_path, {"README.md": "# Hall Monitor: code review of AI-written changes, for IBM Bob\n",
                                 "app/service.py": "def login():\n    return 'ok'\n",
                                 "scripts/setup_demo.py": "print('setup')\n"},
                      config={"test_command": PASSING, "max_mutants": 0, "max_extreme_mutants": 0})
    readme = "# Hall Monitor: code review of AI-written changes, for IBM Bob\n\n## Install and first run\n" + \
        "".join(f"Step {i}: run scripts/setup_demo.py and follow BOB_RUNBOOK.md.\n" for i in range(3))
    (store.root / "README.md").write_text(readme, encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "README.md", "content": readme}}, store)
    (store.root / "app/service.py").write_text("def login():\n    return 'limited'\n", encoding="utf-8")
    EV.record({"tool": "write_file", "input": {"path": "app/service.py", "content": "..."}}, store)
    EV.record({"tool": "execute_command", "input": {"command": "python -m pytest -q"}, "output": "1 passed"}, store)

    result = receipts.verify(store, "**[`README.md`](README.md)** — E1:\n"
                                    "- Added an \"Install and first run\" section pointing to `scripts/setup_demo.py`\n"
                                    "- First line kept as `# Hall Monitor` (D3)\n")
    diffs = {c["state"]["claim"]: c["state"]["evidence"].get("diff", "") for c in fake.calls if "claim" in c["state"]}
    install = next(d for claim, d in diffs.items() if "Install and first run" in claim)
    assert "+## Install and first run" in install and "app/service.py" not in install
    kept = next(r for r in result["rows"] if r["claim"].startswith("First line kept"))
    assert kept["state"] != "contradicted"  # the header's README.md is where it is, not what it says changed
    assert not any(r["code"] == "diff_mismatch" for r in result["rows"])
