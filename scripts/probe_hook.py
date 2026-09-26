"""Probe hook: records the raw stdin payload of every Bob hook event, then allows everything.

Installed by `python scripts/install.py --probe <repo>`; writes <repo>/.hallmonitor/probe.jsonl.
It settles, in one real Bob session, what Hall Monitor cannot learn from the docs: payload field
names per tool, whether hooks fire inside subagents and under `bob run`, and what spawn_subagent sends.
"""
import json
import os
import sys
import time
from pathlib import Path

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    payload = {"_unparsed": raw[:4000]}
root = Path(payload.get("cwd") or os.getcwd()) if isinstance(payload, dict) else Path.cwd()
out = root / ".hallmonitor"
out.mkdir(exist_ok=True)
row = {"t": time.time(), "argv": sys.argv[1:], "cwd": os.getcwd(),
       "env_keys": sorted(k for k in os.environ if k.upper().startswith(("BOB", "HOOK", "CLAUDE"))),
       "payload": payload}
with open(out / "probe.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps(row) + "\n")
sys.exit(0)
