"""Create a fresh copy of the demo login service for a real Bob session and install Hall Monitor into it.

Usage:
  python scripts/setup_demo.py C:/hm-probe --probe    the probe: hooks record raw payloads (PROBE.md)
  python scripts/setup_demo.py C:/hm-demo             the real demo under Hall Monitor (BOB_RUNBOOK.md)
Add --force to replace a folder that already exists.

The hooks and the MCP server run from this Hall Monitor folder. Don't edit it while Bob runs the demo.
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
import install  # noqa: E402


def main(dest, probe=False, force=False):
    sys.stdout.reconfigure(encoding="utf-8")
    dest = Path(dest).resolve()
    if dest.exists():
        if not force:
            sys.exit(f"{dest} already exists. Add --force to replace it.")
        shutil.rmtree(dest, onerror=lambda f, p, e: (Path(p).chmod(0o700), f(p)))
    shutil.copytree(HERE / "demo" / "template", dest)
    git = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-c", "core.autocrlf=false"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "Demo login service: starting point"]):
        subprocess.run(git + args, cwd=dest, check=True)
    install.main(dest, probe=probe)
    print(f"\nDemo repo ready: {dest}")
    print("Next: open it in Bob as a trusted workspace, then follow "
          + ("PROBE.md step 3." if probe else "BOB_RUNBOOK.md step 3."))


if __name__ == "__main__":
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1 or flags - {"--probe", "--force"}:
        sys.exit(__doc__)
    main(args[0], probe="--probe" in flags, force="--force" in flags)
