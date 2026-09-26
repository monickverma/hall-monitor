"""The Hall Pass: one self-contained HTML page per session, built from .hallmonitor/ state."""
import html
import json
from collections import Counter

PRICE_PER_M = 0.042  # $/1M Jev tokens, as observed in TypeSafe's rerank cookbook; an estimate

CHIP = {"allow": ("ok", "allowed"), "approved": ("ok", "approved"), "accept": ("ok", "verified"),
        "rebrief": ("warn", "rebriefed"), "approved_with_note": ("warn", "noted"), "audit": ("warn", "audit"),
        "block": ("bad", "blocked"), "rejected": ("bad", "rejected"), "send_back": ("bad", "sent back"),
        "ask_human": ("warn", "ask human"), "record": ("info", "recorded"), "reject": ("bad", "rejected"),
        "brief": ("info", "briefed"), "new_task": ("info", "new task"), "follow_up": ("info", "briefed"),
        "flag": ("warn", "flagged"), "done": ("info", "done"), "success": ("ok", "success")}
STAGE = {"session_start": "Session", "brief": "Briefing", "ledger": "Decision", "plan": "Plan gate",
         "intent": "Intent", "step": "Tool call", "receipts": "Receipts", "spawn": "Subagent spawn",
         "subagent_return": "Subagent return", "bob_run": "Bob Shell"}

CSS = """
:root{--bg:#f6f4ef;--card:#fffdf8;--ink:#1d1b16;--muted:#6b665c;--line:#e4dfd3;--ok:#1f7a4d;--okbg:#e3f3ea;
--bad:#b3261e;--badbg:#fbe4e1;--warn:#8a5a00;--warnbg:#fbefd6;--info:#2f5d8a;--infobg:#e3ecf6;--accent:#0f62fe}
@media (prefers-color-scheme:dark){:root{--bg:#15140f;--card:#1f1d17;--ink:#f1ede3;--muted:#a39d90;--line:#35322a;
--okbg:#163526;--ok:#6fd6a0;--badbg:#3d1916;--bad:#ff8a80;--warnbg:#3a2c0c;--warn:#f2c14e;--infobg:#172a3d;--info:#8fb8e8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1060px;margin:0 auto;padding:28px 16px 60px}
.pass{display:grid;grid-template-columns:1fr auto;gap:18px;background:var(--card);border:1px solid var(--line);
border-radius:18px;padding:22px 26px;position:relative;overflow:hidden}
.pass:before{content:"";position:absolute;inset:0 auto 0 0;width:8px;background:var(--accent)}
.kicker{letter-spacing:.18em;font-size:12px;font-weight:700;color:var(--muted)}
h1{margin:4px 0 6px;font-size:28px;letter-spacing:-.01em}.goal{color:var(--muted);max-width:720px}
.stamp{align-self:center;transform:rotate(-8deg);border:4px solid currentColor;border-radius:10px;padding:8px 16px;
font-weight:900;font-size:22px;letter-spacing:.08em;text-align:center}
.stamp small{display:block;font-size:11px;letter-spacing:.1em;font-weight:700}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.tile b{display:block;font-size:26px;letter-spacing:-.02em}.tile span{color:var(--muted);font-size:13px}
h2{font-size:17px;margin:28px 0 10px}
section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:6px 16px}
table{width:100%;border-collapse:collapse}td,th{padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
tr:last-child td{border-bottom:0}th{font-size:12px;color:var(--muted);font-weight:600}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}
.warn{background:var(--warnbg);color:var(--warn)}.info{background:var(--infobg);color:var(--info)}
.stage{font-size:12px;color:var(--muted);white-space:nowrap}.why{color:var(--muted);font-size:13px}
.target{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px;word-break:break-all}
.pattern{font-weight:700;color:var(--bad)}s{color:var(--muted)}
.feats{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.feat{border:1px solid var(--line);border-radius:999px;padding:4px 12px;font-size:13px}
.ladder{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.rung{border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:var(--card)}
.rung b{font-size:22px}.rung span{display:block;color:var(--muted);font-size:12px}
@media (max-width:640px){.pass{grid-template-columns:1fr}.ladder{grid-template-columns:repeat(2,1fr)}.hide-sm{display:none}}
"""


def e(x):
    return html.escape(str(x if x is not None else ""))


def chip(action):
    cls, label = CHIP.get(action, ("info", action))
    return f'<span class="chip {cls}">{e(label)}</span>'


def why(ev):
    bits = []
    if ev.get("pattern"):
        bits.append(f'<span class="pattern">{e(ev["pattern"].replace("_", " "))}</span>')
    for did, p in (ev.get("violations") or {}).items():
        if p >= 0.5:
            bits.append(f"breaks {e(did)} ({p:.2f})")
    for agent, p in (ev.get("conflicts") or {}).items():
        if p >= 0.5:
            bits.append(f"conflicts with {e(agent)} ({p:.2f})")
    r = ev.get("risks") or {}
    for k, label in (("destructive", "destructive"), ("mismatch", "not what was declared"), ("off_task", "off-task")):
        if r.get(k, 0) >= 0.5:
            bits.append(f"{label} ({r[k]:.2f})")
    if ev.get("note"):
        bits.append(e(ev["note"]))
    if ev.get("escalated"):
        bits.append(f"escalated: {e(ev['escalated'])}")
    if ev.get("stage") == "ledger" and ev.get("source"):
        bits.append(f"from {e(ev['source'])}")
    if ev.get("stage") == "receipts":
        counts = Counter((ev.get("verdicts") or {}).values())
        bits.append(" · ".join(f"{n} {v}" for v, n in counts.most_common()))
        if "jev+audit" in (ev.get("tiers") or []):
            bits.append("used an explore-subagent audit")
        if ev.get("survived"):
            bits.append(f"{ev['survived']}/{ev['mutants']} sabotage mutants survived")
    if ev.get("missing_sections"):
        bits.append("missing " + e(", ".join(ev["missing_sections"])))
    return " · ".join(bits)


def write_hall_pass(store):
    all_events = store.events()
    events = [x for x in all_events if x.get("stage") not in ("error", "mcp_call")]
    mcp_calls = [x for x in all_events if x.get("stage") == "mcp_call"]
    sess = store.session()
    receipts = json.loads((store.dir / "receipts.json").read_text(encoding="utf-8")) \
        if (store.dir / "receipts.json").exists() else None
    tok = sum(x.get("tokens", 0) for x in events)
    judged = [x for x in events if x.get("stage") in ("intent", "step", "plan", "spawn")]
    stopped = [x for x in judged if x.get("action") in ("block", "ask_human")]
    patterns = [x["pattern"] for x in events if x.get("pattern")]
    agents = {x.get("agent") for x in events if x.get("agent") and x.get("agent") != "main"}
    last_r = [x for x in events if x.get("stage") == "receipts"]
    rounds = len(last_r)
    status = (last_r[-1]["action"] if last_r else "in_progress")
    stamp = {"accept": ("ok", "VERIFIED"), "send_back": ("bad", "SENT BACK"), "audit": ("warn", "AUDITING")}.get(
        status, ("warn", "IN PROGRESS"))
    ladder = Counter()
    for x in events:
        if x.get("stage") in ("intent", "step"):
            ladder[{"deep_look": "deep", "human": "human"}.get(x.get("escalated"), "jev")] += 1
        for t in x.get("tiers") or []:
            ladder[{"jev": "jev", "jev+audit": "bob", "jev_deep": "deep", "bob_shell_audit": "bob"}[t]] += 1

    feats = ["Lifecycle hooks (SessionStart · UserPromptSubmit · PreToolUse · PostToolUse · Stop)",
             f"MCP server: {len(mcp_calls)} calls (declare_intent · explain_block · record_decision · submit_claims · hall_pass)",
             "Custom modes: 🛂 Supervised · 🔎 Receipts Auditor (no edit group)"]
    if any(x.get("stage") in ("spawn", "subagent_return") for x in events):
        feats.append("spawn_subagent supervised: briefs checked before start, summaries on return")
    runs = [x for x in events if x.get("stage") == "bob_run"]
    if runs:
        costs = [((x.get("bob_stats") or {}).get("session_costs")) for x in runs]
        feats.append(f"Bob Shell headless runs: {len(runs)} (session_costs: {', '.join(str(c) for c in costs)})")
    if any(x.get("stage") == "ledger" and any(ext in str(x.get("source", "")).lower() for ext in (".pdf", ".docx", ".xlsx"))
           for x in events):
        feats.append("Document understanding: rules read from policy documents")
    if agents:
        feats.append(f"Parallel subagents checked: {', '.join(sorted(agents))}")
    if any(x.get("stage") == "plan" for x in events):
        feats.append("Plan mode → certified plan gate")
    if ladder["bob"]:
        feats.append("Explore-subagent audits")

    rows = []
    for x in events:
        if x.get("stage") in ("session_start",):
            continue
        target = x.get("target") or x.get("text") or ", ".join((x.get("decisions_added") or [])) or \
            (f"{x.get('claims')} claims" if x.get("stage") == "receipts" else "")
        who = f' <span class="stage">[{e(x["agent"])}]</span>' if x.get("agent") and x.get("agent") != "main" else ""
        rows.append(f'<tr><td class="stage">{e(STAGE.get(x["stage"], x["stage"]))}{who}</td>'
                    f'<td>{chip(x.get("verdict") or x.get("action"))}</td>'
                    f'<td><div class="target">{e(str(target)[:140])}</div><div class="why">{why(x)}</div></td>'
                    f'<td class="stage hide-sm">{x.get("tokens", 0):,} tok</td></tr>')

    ledger_rows = []
    rows_all = store.ledger()
    dead = {r["supersedes"] for r in rows_all if r.get("supersedes")}
    for r in rows_all:
        text = f"<s>{e(r['text'])}</s>" if r["id"] in dead else e(r["text"])
        ledger_rows.append(f'<tr><td><b>{e(r["id"])}</b></td><td>{text}</td>'
                           f'<td class="why">{e(r.get("kind"))}</td><td class="why">{e(r["source"])}</td></tr>')

    rec = ""
    if receipts:
        rec = "".join(f'<tr><td>{chip("accept" if r["action"] == "accept" else r["action"])}</td>'
                      f'<td>{e(r["claim"])}<div class="why">{e(r["verdict"])} ({r["confidence"]}) · judged by '
                      f'{e({"jev": "Jev", "jev_deep": "Jev deep look", "jev+audit": "Jev + explore-subagent audit", "bob_shell_audit": "Jev + Bob Shell auditor"}.get(r["tier"], r["tier"]))}</div></td></tr>'
                      for r in receipts["rows"])
        s = receipts["sabotage"]
        rec += (f'<tr><td class="stage">evidence</td><td class="why">tests '
                f'{"pass" if receipts["tests"]["passed"] else "FAIL"} · sabotage {s["killed"]}/{s["mutants"]} '
                f'mutants killed</td></tr>')

    tiles = [(len(judged), "actions & intents judged"), (len(stopped), "stopped before they ran"),
             (len(patterns), "rationalizations named"), (rounds, "receipt rounds"),
             (f"${tok * PRICE_PER_M / 1e6:.4f}", f"Jev cost ({tok:,} tokens)")]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Hall Pass</title><style>{CSS}</style></head>
<body><main>
<div class="pass"><div><div class="kicker">HALL MONITOR · HALL PASS</div><h1>Supervised Bob session</h1>
<div class="goal">{e(sess.get('goal') or 'No goal recorded')}</div></div>
<div class="stamp {stamp[0]}" style="color:var(--{stamp[0]})">{stamp[1]}<small>RECEIPTS</small></div></div>
<div class="tiles">{''.join(f'<div class="tile"><b>{e(v)}</b><span>{e(k)}</span></div>' for v, k in tiles)}</div>
<h2>Escalation ladder</h2><div class="ladder">
<div class="rung"><b>{ladder['jev']}</b><span>Jev, one parallel request</span></div>
<div class="rung"><b>{ladder['deep']}</b><span>Jev deep look (full evidence)</span></div>
<div class="rung"><b>{ladder['bob']}</b><span>Bob explore-subagent audit</span></div>
<div class="rung"><b>{ladder['human']}</b><span>asked the human</span></div></div>
<h2>Timeline</h2><section><table>{''.join(rows)}</table></section>
<h2>Decision ledger</h2><section><table>{''.join(ledger_rows) or '<tr><td>none</td></tr>'}</table></section>
<h2>Receipts</h2><section><table>{rec or '<tr><td>No claims submitted yet</td></tr>'}</table></section>
<h2>IBM Bob features in play</h2><div class="feats">{''.join(f'<span class="feat">{e(f)}</span>' for f in feats)}</div>
</main></body></html>"""
    path = store.dir / "hall-pass.html"
    path.write_text(page, encoding="utf-8")
    summary = (f"{len(judged)} actions/intents judged, {len(stopped)} stopped, {len(patterns)} rationalizations "
               f"named, receipts: {stamp[1]}, Jev cost ${tok * PRICE_PER_M / 1e6:.4f}")
    return str(path), summary
