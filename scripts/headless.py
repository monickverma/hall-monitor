"""CI gate: run Bob headlessly in the Supervised mode, then fail the build unless Receipts verified the work.

Usage: python scripts/headless.py <repo> "<task>"

`bob run` pre-approves every tool, so nobody reviews the agent's actions in CI. Hall Monitor's hooks
are the gate while it works, and Receipts decides the exit code afterwards.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hallmonitor import bob, report  # noqa: E402
from hallmonitor.receipts import task_rounds  # noqa: E402
from hallmonitor.store import Store  # noqa: E402


def bob_failure(data):
    """Why `bob run` gave no result, in words an operator can act on; None when it ran."""
    if data.get("status") != "unparsed" or not data.get("exit_code"):
        return None
    err = data.get("error") or "no output"
    hint = ""
    if "license" in err.lower():
        hint = " Run `bob` once interactively to read and accept IBM's license, or set HM_BOB_ACCEPT_LICENSE=1."
    elif "api key" in err.lower():
        hint = " Create a key at bob.ibm.com (Admin, API Keys) and set BOB_API_KEY; a 'general' key also needs HM_BOB_TEAM_ID."
    return f"Bob Shell exited {data['exit_code']} before the task ran: {err}{hint}"


def main(repo, task):
    sys.stdout.reconfigure(encoding="utf-8")
    data = bob.run_supervised(repo, task)
    if data is None:
        sys.exit("Bob Shell (`bob`) is not installed or not on PATH.")
    failure = bob_failure(data)
    if failure:
        print(failure, file=sys.stderr)
    store = Store(repo)
    path, summary = report.write_hall_pass(store)
    receipts = task_rounds(store.events())  # the main agent's rounds: a subagent's verdict covers only its part
    verified = bool(receipts) and receipts[-1]["action"] == "accept"
    print(json.dumps({"bob_status": data.get("status"), "bob_stats": data.get("stats"),
                      "receipts": receipts[-1]["action"] if receipts else "none", "hall_pass": path,
                      "summary": summary}, indent=2))
    sys.exit(0 if verified else 1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
