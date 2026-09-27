"""Summarize a probe session: what Bob's hooks actually sent, and the answers Hall Monitor depends on.

Usage: python scripts/probe_report.py <repo>
Reads <repo>/.hallmonitor/probe.jsonl (hook payloads) and events.jsonl (MCP calls, if the hall-monitor
MCP server was connected during the probe).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def field(p, *keys):
    for k in keys:
        if isinstance(p, dict) and k in p:
            return p[k]
    return None


def main(repo):
    sys.stdout.reconfigure(encoding="utf-8")
    d = Path(repo) / ".hallmonitor"
    rows = load(d / "probe.jsonl")
    if not rows:
        sys.exit(f"No probe data in {d}. Install with --probe and follow PROBE.md first.")
    events, keys, tool_keys, sessions = defaultdict(int), defaultdict(set), defaultdict(set), defaultdict(set)
    spawns = []
    for i, r in enumerate(rows):
        p = r["payload"]
        ev = field(p, "event", "hook_event_name") or "?"
        tool = field(p, "tool", "tool_name")
        inp = field(p, "input", "tool_input")
        events[ev] += 1
        keys[ev] |= set(p) if isinstance(p, dict) else set()
        if tool and isinstance(inp, dict):
            tool_keys[tool] |= set(inp)
        sessions[field(p, "session_id")].add(ev)
        if tool == "spawn_subagent":
            spawns.append((i, ev, p))

    print("1. Events seen:", dict(events))
    print("\n2. Top-level payload keys per event:")
    for ev, ks in keys.items():
        print(f"   {ev}: {sorted(ks)}")
    print("\n3. Tool input keys per tool (Hall Monitor's payload.py must read these):")
    for t, ks in sorted(tool_keys.items()):
        print(f"   {t}: {sorted(ks)}")
    print("\n4. Assistant text in any payload?",
          any(any(k in (r["payload"] or {}) for k in ("assistant_message", "message", "last_assistant_message"))
              for r in rows if isinstance(r["payload"], dict)))

    print("\n5. Subagents:")
    pre = [i for i, ev, _ in spawns if ev == "PreToolUse"]
    post = [i for i, ev, _ in spawns if ev == "PostToolUse"]
    print(f"   spawn_subagent PreToolUse: {len(pre)}  PostToolUse: {len(post)}")
    if spawns:
        print("   spawn input example:", json.dumps(field(spawns[0][2], "input", "tool_input"))[:300])
    inside = 0
    for a, b in zip(pre, post):
        inside += sum(1 for r in rows[a + 1:b]
                      if field(r["payload"], "event", "hook_event_name") in ("PreToolUse", "PostToolUse")
                      and field(r["payload"], "tool", "tool_name") != "spawn_subagent")
    print(f"   hook events between a subagent's spawn and its return: {inside}"
          f" -> hooks {'DO' if inside else 'probably do NOT'} fire inside subagents"
          " (check that the subagent actually used tools)")
    print(f"   distinct session_ids: {len(sessions)} {dict((str(k)[:12], sorted(v)) for k, v in sessions.items())}")

    calls = [e for e in load(d / "events.jsonl") if e.get("stage") == "mcp_call"]
    if calls:
        agents = defaultdict(int)
        for c in calls:
            agents[c.get("agent") or "main/unspecified"] += 1
        print("\n6. hall-monitor MCP calls by agent:", dict(agents),
              "-> subagents CAN call MCP" if any(a not in ("main", "main/unspecified") for a in agents) else "")
    else:
        print("\n6. No hall-monitor MCP calls logged (was the MCP server connected?)")

    # v4.1 checks
    post_cmd = [r["payload"] for r in rows if field(r["payload"], "event", "hook_event_name") == "PostToolUse"
                and field(r["payload"], "tool", "tool_name") in ("execute_command", "run_command", "shell")]
    print("\n7. PostToolUse on commands:", len(post_cmd))
    for p in post_cmd[:1]:
        out = field(p, "tool_response", "tool_output", "output", "result")
        nested = out if isinstance(out, dict) else {}
        code = field(p, "exit_code", "exitCode", "returncode") or field(nested, "exit_code", "exitCode", "returncode")
        print(f"   carries output: {out is not None} (receipts need it)   exit code: {code!r} "
              f"({'receipts use it' if code is not None else 'none: pass/fail is inferred from the output'})")
    kinds = sorted({t for c in calls if c.get("tool") == "submit_claims" for t in (c.get("claim_types") or [])})
    print("\n8. submit_claims item types Bob sent:", kinds or "none (ask Bob to submit a claim with evidence IDs)",
          "-> evidence-carrying claims work" if "dict" in kinds else "")
    import subprocess
    refs = subprocess.run(["git", "for-each-ref", "refs/hallmonitor"], cwd=repo, capture_output=True, text=True).stdout
    print("\n9. Checkpoint refs:", len(refs.splitlines()),
          "-> now use Bob's rollback once and confirm it still works" if refs else
          "(none yet: run a passing test in Bob, or create one by hand as PROBE.md step 8 says)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
