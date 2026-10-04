"""Check that Hall Monitor is ready to supervise Bob, before a task finds out the hard way.

Usage:
  python scripts/doctor.py [path-to-repo]          offline checks (free)
  python scripts/doctor.py [path-to-repo] --live   also one tiny Jev request and one tiny `bob run` (about $0.03)

Checks Python, the packages, the keys (as Bob will see them: Bob starts Hall Monitor without your shell's
environment, so on Windows the keys must be saved with `setx`), Bob Shell, and, given a repo, that Hall Monitor's
hooks, MCP server, modes and skills are installed there and point at files that exist. Exit code 1 if anything fails.
Real Bob, Oct 4: an expired BOB_API_KEY showed up only as "Request Failed" in the middle of a run.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "scripts"))
results = []


def report(ok, what, fix=""):
    results.append(ok)
    mark = {True: "ok  ", False: "FAIL", None: "warn"}[ok]
    print(f"[{mark}] {what}" + (f"\n         -> {fix}" if fix and ok is not True else ""))


def check_python():
    report(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Hall Monitor needs Python 3.11 or newer.")
    for mod, pip, needed in (("typesafe_sdk", "typesafe-sdk", True), ("pytest", "pytest", True),
                             ("reportlab", "reportlab", False)):
        try:
            __import__(mod)
            report(True, f"package {pip}")
        except ImportError:
            report(False if needed else None, f"package {pip} missing",
                   f"pip install -r {HERE / 'requirements.txt'}")


def saved_key(name):
    """The value `setx` saved for the user (Windows), or None."""
    if os.name != "nt":
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check_keys(live):
    from hallmonitor import jev
    # A shell keeps the environment it started with: after `setx NAME <new key>`, an open terminal still has the old
    # one. Real Bob, Oct 4: a replaced, expired BOB_API_KEY was still in the shell that ran the checks.
    for name in ("TYPESAFE_API_KEY", "BOB_API_KEY"):
        saved, here = saved_key(name), os.environ.get(name)
        if saved and here and saved != here:
            report(None, f"{name} in this shell differs from the one saved with setx",
                   "Open a new terminal (and restart Bob) so both use the saved key. These checks use the saved one.")
            os.environ[name] = saved
    jev.load_key_from_user_env()  # the same lookup the hooks and the MCP server do
    for name, why in (("TYPESAFE_API_KEY", "Jev, which judges intents and claims"),
                      ("BOB_API_KEY", "Bob Shell runs and the Receipts auditor (not needed for the Bob IDE alone)")):
        have = bool(os.environ.get(name))
        report(have if name == "TYPESAFE_API_KEY" else (have or None), f"{name} {'set' if have else 'not set'} ({why})",
               f'Save it where Bob can read it: setx {name} "<your key>" (Windows), then restart Bob.')
    if live and os.environ.get("TYPESAFE_API_KEY"):
        from hallmonitor import questions as Q
        try:
            jev.ask({"action": {"declared_intent": "Run the test suite."}}, {"destructive": Q.DESTRUCTIVE})
            report(True, "Jev answers")
        except Exception as e:  # noqa: BLE001 - any failure here is the finding
            report(False, f"Jev request failed: {type(e).__name__}", "Check TYPESAFE_API_KEY and the network.")


def check_bob(live):
    exe = shutil.which("bob")
    if not exe:
        report(None, "Bob Shell (bob) not on PATH", "Needed for headless runs and the Receipts auditor; the Bob IDE works "
                                                     "without it.")
        return
    v = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60)
    report(v.returncode == 0, f"Bob Shell {v.stdout.split()[0] if v.stdout.split() else '?'}")
    if live and os.environ.get("BOB_API_KEY"):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([exe, "run", "Reply with the single word: ready", "-f", "json", "--max-turns", "1",
                                "--max-cost", "0.05", "--workspace", tmp], capture_output=True, text=True, timeout=180,
                               stdin=subprocess.DEVNULL)
        out = (r.stdout or "") + (r.stderr or "")
        ok = '"status":"success"' in out.replace(" ", "")
        report(ok, "Bob Shell answers" if ok else "Bob Shell request failed",
               "A 'Request Failed' here usually means BOB_API_KEY expired or was revoked: make a new key in your IBM "
               "Bob account and setx it.")


def check_repo(repo):
    repo = Path(repo).resolve()
    report((repo / ".git").exists(), f"{repo} is a git repository", "Hall Monitor diffs against git: run git init.")
    bob = repo / ".bob"
    settings = bob / "settings.json"
    if not settings.exists():
        report(False, "no .bob/settings.json", f"python {HERE / 'scripts' / 'install.py'} {repo}")
        return
    hooks = json.loads(settings.read_text(encoding="utf-8")).get("hooks") or {}
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        cmds = [h.get("command", "") for e in hooks.get(event, []) for h in e.get("hooks", [])]
        mine = [c for c in cmds if "hm_hook.py" in c]
        if not mine:
            report(False, f"hook {event} not installed", f"python {HERE / 'scripts' / 'install.py'} {repo}")
            continue
        script = mine[0].split()[-1].strip('"')
        report(Path(script).exists(), f"hook {event} -> {script}",
               "The hook points at a file that has moved: run install.py again.")
    mcp = bob / "mcp.json"
    server = (json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers") or {}).get("hall-monitor") \
        if mcp.exists() else None
    if not server:
        report(False, "MCP server hall-monitor not in .bob/mcp.json", f"python {HERE / 'scripts' / 'install.py'} {repo}")
    else:
        report(Path(server.get("command", "")).exists() and all(Path(a).exists() for a in server.get("args", [])),
               f"MCP server: {server.get('command')} {' '.join(server.get('args', []))}",
               "The Python or hm_mcp.py it names has moved: run install.py again.")
        report(Path(server.get("cwd", "")).resolve() == repo, "MCP server runs in this repo",
               "mcp.json was copied from another repo: run install.py here.")
    modes = bob / "custom_modes.yaml"
    report(modes.exists() and "# hall-monitor modes" in modes.read_text(encoding="utf-8"),
           "Supervised and Receipts Auditor modes", "run install.py again")
    report((bob / "skills" / "hall-monitor-protocol" / "SKILL.md").exists(), "hall-monitor-protocol skill",
           "run install.py again")
    ignore = repo / ".gitignore"
    report(ignore.exists() and ".hallmonitor/" in ignore.read_text(encoding="utf-8").splitlines(),
           ".hallmonitor/ is git-ignored", "Add .hallmonitor/ to .gitignore, or Hall Monitor's records show in diffs.")
    print("\nIn the Bob IDE, also check by hand: the folder is a TRUSTED workspace (hooks respect trust), "
          "Settings > Hooks lists five hooks, and the hall-monitor MCP server is approved and connected.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    live = "--live" in sys.argv
    check_python()
    check_keys(live)
    check_bob(live)
    if args:
        check_repo(args[0])
    failed = results.count(False)
    print(f"\n{failed} failed, {results.count(None)} warning(s).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
