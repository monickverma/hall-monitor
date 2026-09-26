"""Replay a scripted Bob session through the real hooks and the real MCP server (real Jev calls).

Usage: python simulate.py [--out demo/run]

MCP calls go through an actual stdio JSON-RPC session with hm_mcp.py, exactly as Bob would make them.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from demo import scenario  # noqa: E402
from hallmonitor import hook, jev  # noqa: E402
from hallmonitor.store import Store  # noqa: E402

def clean(text):
    """Printed output never carries this machine's absolute paths (they contain the local user name)."""
    for root in {str(HERE.resolve()), str(HERE)}:
        text = text.replace(root.replace("\\", "\\\\"), "hall-monitor").replace(root, "hall-monitor")
    return text


LABEL = {"allow": "ALLOW", "rebrief": "REBRIEF", "block": "BLOCK", "ask_human": "ASK", "send_back": "SENDBACK",
         "accept": "VERIFIED", "audit": "AUDIT", "brief": "BRIEF", "new_task": "BRIEF", "follow_up": "BRIEF",
         "approved": "APPROVED", "approved_with_note": "NOTED", "rejected": "REJECTED", "record": "RECORDED",
         "reject": "REJECTED", "flag": "FLAGGED", "ok": "OK", "needs_evidence": "EVIDENCE?", "stuck": "STUCK"}


def cite(claims, store):
    """Resolve the scenario's symbolic citations against the real evidence ledger, as Bob would after
    calling list_evidence: "@test" is the newest test run, "@edit:<path>" the newest edit of that file."""
    rows = store.evidence()

    def newest(pred):
        ids = [r["id"] for r in rows if pred(r)]
        return ids[-1] if ids else "E0"

    def one(ref):
        if ref == "@test":
            return newest(lambda r: r["kind"] == "test")
        if ref.startswith("@edit:"):
            return newest(lambda r: r["kind"] == "edit" and r.get("file") == ref[6:])
        return ref
    return [{**c, "evidence": [one(x) for x in c["evidence"]]} if isinstance(c, dict) else c for c in claims]


class MCP:
    """A real MCP stdio client session with the Hall Monitor server."""

    def __init__(self, root):
        env = {**os.environ, "HM_ROOT": str(root), "HM_DISABLE_BOB_SHELL": "1"}
        self.p = subprocess.Popen([sys.executable, str(HERE / "hm_mcp.py")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env, cwd=root)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "simulated-bob", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.tools = [t["name"] for t in self.rpc("tools/list", {})["tools"]]

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())["result"]

    def call(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return r["content"][0]["text"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


def setup(dest):
    if dest.exists():
        shutil.rmtree(dest, onerror=lambda f, p, e: (Path(p).chmod(0o700), f(p)))
    shutil.copytree(HERE / "demo" / "template", dest)
    g = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com", "-c", "core.autocrlf=false"]
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "initial"]):
        subprocess.run(g + args, cwd=dest, check=True)
    Store(dest).dir.joinpath("config.json").write_text(json.dumps({"max_mutants": 6}))


def apply(step, dest):
    a = step.get("apply") or {}
    if "path" in a:
        p = dest / a["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(a["content"], encoding="utf-8")
        return ""
    r = subprocess.run(step["input"]["command"], cwd=dest, shell=True, capture_output=True, text=True)
    return (r.stdout + r.stderr)[-800:]


def summarize(ev):
    bits = []
    if ev.get("pattern"):
        bits.append(f"pattern={ev['pattern']}")
    bits += [f"{k}={v:.2f}" for k, v in (ev.get("risks") or {}).items()
             if v >= 0.3 and k not in ("verified", "unsupported", "contradicted")]
    if ev.get("escalated"):
        bits.append(f"escalated={ev['escalated']}")
    return " ".join(bits)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "demo" / "run"))
    dest = Path(ap.parse_args().out).resolve()
    setup(dest)
    store = Store(dest)
    mcp = MCP(dest)
    print(f"MCP server up; tools: {', '.join(mcp.tools)}\n")
    t0 = time.time()
    for i, s in enumerate(scenario.STEPS, 1):
        n_before = len(store.events())
        after = None
        if "mcp" in s:
            if s["mcp"] == "submit_claims":
                s = {**s, "args": {**s["args"], "claims": cite(s["args"]["claims"], store)}}
            text = mcp.call(s["mcp"], s["args"])
            if s["mcp"] == "submit_claims" and "AUDIT NEEDED" in text:
                ev = store.events()[-1]
                idx = [int(m) for m in re.findall(r"AUDIT NEEDED for claim (\d+)", text)]
                print(f"{i:>2}. {'AUDIT':9} {s['label']:<46} -> Bob spawns an explore subagent (claims {idx})")
                for line in text.splitlines()[:8]:
                    print(clean(f"      | {line}"))
                rows = json.loads((store.dir / "receipts.json").read_text(encoding="utf-8"))["rows"]
                notes = {str(k): scenario.audit_for(rows[k]["claim"]) for k in idx}
                text = mcp.call("submit_claims", {**s["args"], "audit_notes": notes})
                s = {**s, "label": "  resubmitted with the subagent's audit"}
            ev = (store.events()[n_before:] or [{}])[-1]
            action = ev.get("verdict") or ev.get("action") or "ok"
            code = 0
            lines = text.splitlines()
        else:
            payload = {"event": s["hook"], "cwd": str(dest), "session_id": "demo"}
            if s["hook"] == "UserPromptSubmit":
                payload["prompt"] = s["prompt"]
            if s["hook"] in ("PreToolUse", "PostToolUse"):
                payload.update(tool=s["tool"], input=s["input"])
            code, out, err = hook.handle(payload)
            ev = (store.events()[n_before:] or [{}])[-1]
            action = ev.get("action", "allow" if code == 0 else "block")
            lines = (err or "").splitlines()
            if s["hook"] == "PreToolUse" and code == 0 and "apply" in s:
                output = apply(s, dest)
                hook.handle({**payload, "event": "PostToolUse", "output": output})
            if s["hook"] == "PreToolUse" and code == 0 and s.get("post_output"):
                n_mid = len(store.events())
                hook.handle({**payload, "event": "PostToolUse", "output": s["post_output"]})
                ret = (store.events()[n_mid:] or [{}])[-1]
                if ret.get("stage") == "subagent_return":
                    after = f"{i:>2}. {LABEL.get(ret['action'], ret['action']):9} {'  …it returns its summary':<46} {summarize(ret)}"
        print(f"{i:>2}. {LABEL.get(action, action):9} {s['label']:<46} {summarize(ev)}")
        show = lines if (code == 2 or action in ("rejected", "send_back", "reject", "audit", "approved_with_note",
                                                 "needs_evidence", "stuck", "ask_human")
                         or s.get("mcp") in ("explain_block", "list_evidence")
                         or (lines and lines[0].startswith("Hall Monitor notes"))) else lines[:1]
        for line in show[:12]:
            print(clean(f"      | {line}"))
        if after:
            print(after)
    mcp.close()

    events = store.events()
    tok = sum(e.get("tokens", 0) for e in events)
    for e in [e for e in events if e.get("stage") == "error"]:
        print("ERROR:", e["error"], "\n", e["trace"])
    receipts = store.evidence()
    print(f"\n{len(events)} logged events, {len(receipts)} receipts "
          f"({sum(1 for r in receipts if r['kind'] == 'checkpoint')} checkpoints), {tok:,} Jev input tokens "
          f"({jev.MODEL}), {time.time() - t0:.0f}s, ${jev.cost(tok):.4f}\n"
          f"Hall Pass: {(store.dir / 'hall-pass.html').relative_to(HERE.resolve()).as_posix()}")


if __name__ == "__main__":
    main()
