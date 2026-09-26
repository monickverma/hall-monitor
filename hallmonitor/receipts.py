"""AFTER: Receipts. Every claim Bob makes about its work is checked against executed evidence.

Escalation ladder for a claim: Jev on focused evidence -> Jev deep look on all evidence -> a Bob
`explore` subagent (read-only, fresh context, so none of the builder's rationalizations) audits the
code and reports back -> Jev judges the claim again with that audit as evidence -> human.

Entry points: the MCP tool submit_claims (verdicts return straight to Bob), a write to CLAIMS.md
(PreToolUse, so a blocked write shows Bob the verdicts), and the Stop hook as a backstop.
"""
import json
import re
import time

from . import bob, brief, gitutil, jev, policy, questions as Q

# Which evidence each kind of claim is judged on (less noise, fewer tokens).
EVIDENCE_FOR = {
    "implemented": ("changed_files", "diff"),
    "fixed": ("changed_files", "diff", "tests"),
    "unchanged": ("changed_files",),
    "tests_added": ("changed_files", "diff", "tests", "sabotage"),
    "tests_pass": ("tests", "commands_the_agent_ran"),
    "other_claim": ("changed_files", "diff"),
    "obligation": ("changed_files", "diff", "tests", "sabotage"),
}


def _relevant_diff(changes, claim, budget=2500):
    """Put files the claim mentions first, so the evidence the claim is about survives truncation."""
    words = set(re.findall(r"[A-Za-z_][\w./]*", claim.lower()))

    def mentioned(path):
        stem = path.lower().rsplit("/", 1)[-1]
        return path.lower() in words or stem in words or stem.split(".")[0] in words
    ordered = dict(sorted(changes.items(), key=lambda kv: not mentioned(kv[0])))
    return gitutil.diff_text(ordered, budget)


def verify(store, claims_or_summary, audit_notes=None, source="mcp"):
    t0 = time.time()
    cfg, sess = store.config(), store.session()
    audit_notes = {int(k): v for k, v in (audit_notes or {}).items()}
    if isinstance(claims_or_summary, str):
        sents = brief.sentences(claims_or_summary, limit=20)
        kinds, usage = jev.ask({"sentences": sents}, {f"kind_{i}": Q.claim_kind(i) for i in range(len(sents))})
        tok = jev.tokens(usage)
        claims = [(s, kinds[f"kind_{i}"]["choice"]) for i, s in enumerate(sents)
                  if kinds[f"kind_{i}"]["choice"] != "not_a_claim"]
    else:
        items = [c for c in claims_or_summary if c.strip()]
        kinds, usage = jev.ask({"sentences": items}, {f"kind_{i}": Q.claim_kind(i) for i in range(len(items))})
        tok = jev.tokens(usage)
        claims = [(c, kinds[f"kind_{i}"]["choice"]) for i, c in enumerate(items)]
    # Obligations from the ledger are implicit claims: the finished work must satisfy them.
    claims += [(f"The finished work satisfies the project rule {d['id']}: \"{d['text']}\"", "obligation")
               for d in store.active_decisions(kind="obligation")]

    docs = {cfg["claims_file"].lower()}
    changes = {f: c for f, c in gitutil.changes(store.root, sess.get("base")).items()
               if f.lower() not in docs and not f.lower().endswith((".md", ".txt", ".rst", ".pdf"))}
    tests = gitutil.run_tests(store.root, cfg["test_command"])
    needs_sabotage = tests["passed"] and any(k in ("tests_added", "tests_pass", "implemented", "fixed",
                                                   "obligation") for _, k in claims)
    sab = gitutil.sabotage(store.root, changes, cfg["test_command"], cfg["max_mutants"]) if needs_sabotage \
        else {"mutants": 0, "killed": 0, "survived": [], "note": "not run"}
    changed_files = {f: c["status"] for f, c in changes.items()}

    def verdict_job(i, deep=False):
        claim, kind = claims[i]
        full = {"changed_files": changed_files, "diff": _relevant_diff(changes, claim, 7000 if deep else 2500),
                "tests": tests, "sabotage": sab,
                "commands_the_agent_ran": [c["command"] for c in sess.get("commands", [])]}
        keys = list(full) if deep else list(EVIDENCE_FOR.get(kind, full))
        evidence = {k: full[k] for k in keys}
        if i in audit_notes:
            evidence["independent_audit"] = audit_notes[i][:3000]
        return {"claim": claim, "claim_kind": kind, "evidence": evidence}, {"verdict": Q.VERDICT}

    def judge(ans, cost):
        dist = ans["verdict"]["probabilities"]
        worlds, reveal = policy.exclusive(dist, "verified")
        return policy.decide(worlds, reveal, policy.CLAIM_HARM, escalate_cost=cost, risks=dist)

    n = len(claims)
    risk_jobs = [({"change": {"file": f, "status": c["status"],
                              "added": "\n".join(t for _, t in c["added"][:40])}}, {"risk": Q.FILE_RISK})
                 for f, c in changes.items()]
    results = jev.ask_many([verdict_job(i, deep=i in audit_notes) for i in range(n)] + risk_jobs)
    answers = [a for a, _ in results[:n]]
    tok += sum(jev.tokens(u) for _, u in results)
    decisions = [judge(a, cfg["claim_escalate_cost"]) for a in answers]
    tiers = ["jev+audit" if i in audit_notes else "jev" for i in range(n)]

    # Tier 2: a deep look, with all evidence and a longer diff, only where it could change the outcome.
    redo = [i for i, d in enumerate(decisions) if d.escalate and i not in audit_notes]
    for i, (a, u) in zip(redo, jev.ask_many([verdict_job(i, deep=True) for i in redo])):
        answers[i], decisions[i], tiers[i] = a, judge(a, cfg["bob_audit_cost"]), "jev_deep"
        tok += jev.tokens(u)

    # Tier 3: still worth more scrutiny -> an independent Bob audit (Bob Shell if installed, else
    # ask the supervised Bob to spawn a read-only explore subagent and resubmit with its findings).
    audits = []
    for i, d in enumerate(decisions):
        if tiers[i] == "jev_deep" and d.escalate:
            brief_text = audit_brief(claims[i][0], changed_files, tests, sab)
            notes = bob.shell_audit(store.root, brief_text)
            if notes:
                audit_notes[i] = notes
                a, u = jev.ask(*verdict_job(i, deep=True))
                answers[i], decisions[i], tiers[i] = a, judge(a, None), "bob_shell_audit"
                tok += jev.tokens(u)
            else:
                audits.append({"index": i, "claim": claims[i][0], "brief": brief_text})

    rows = [{"index": i, "claim": c, "kind": k, "verdict": a["verdict"]["choice"],
             "confidence": round(a["verdict"]["confidence"], 2), "tier": t, **d.as_dict()}
            for i, ((c, k), a, d, t) in enumerate(zip(claims, answers, decisions, tiers))]
    for r in rows:
        if any(x["index"] == r["index"] for x in audits):
            r["action"] = "audit"
    risky = [(st["change"]["file"], round(ans["risk"]["score"], 2))
             for (st, _), (ans, _) in zip(risk_jobs, results[n:]) if ans["risk"]["score"] >= 2.2]

    result = {"rows": rows, "tests": tests, "sabotage": sab, "risky_files": risky, "audits": audits}
    store.write_report("receipts.md", report(result))
    store.write_report("receipts.json", json.dumps(result, indent=2))
    status = "send_back" if any(r["action"] == "send_back" for r in rows) else \
        "audit" if audits else "accept"
    store.log({"stage": "receipts", "source": source, "claims": len(rows), "action": status,
               "verdicts": {r["claim"][:80]: r["verdict"] for r in rows}, "tiers": tiers,
               "risky_files": risky, "mutants": sab["mutants"], "survived": len(sab["survived"]),
               "tokens": tok, "ms": int((time.time() - t0) * 1000)})
    result["status"] = status
    return result


def audit_brief(claim, changed_files, tests, sab):
    lines = [f"Audit this claim independently: \"{claim}\"",
             f"Changed files: {', '.join(changed_files) or 'none'}.",
             f"Test run: {'passing' if tests['passed'] else 'failing'}.",
             f"Sabotage: {sab['killed']}/{sab['mutants']} mutants killed."]
    lines += [f"Surviving mutant: {m['file']}:{m['line']} `{m['from']}` -> `{m['to']}`" for m in sab["survived"]]
    lines.append("Read the code and tests; do not edit anything. Report exactly what the code and tests "
                 "show about the claim, citing file:line, and say plainly whether the claim holds.")
    return "\n".join(lines)


def message(result):
    """What Bob sees: verdicts, the evidence behind the bad ones, and what to do next."""
    rows = result["rows"]
    if result["status"] == "accept":
        out = [f"Receipts: all {len(rows)} claims verified. Tests pass; "
               f"{result['sabotage']['killed']}/{result['sabotage']['mutants']} sabotage mutants were caught."]
        if result["risky_files"]:
            out.append("Recommend a Review-mode pass on: " + ", ".join(f for f, _ in result["risky_files"]))
        return "\n".join(out)
    out = ["Receipts: some claims are not backed by the evidence."]
    for r in rows:
        if r["action"] in ("send_back", "audit", "flag"):
            p_false = r["risks"].get("contradicted", 0) + r["risks"].get("unsupported", 0)
            label = r["verdict"].upper() if r["verdict"] != "verified" else f"NOT PROVEN, p(false)={p_false:.2f}"
            out.append(f"- [{label}] ({r['action']}) {r['claim']}")
    for m in result["sabotage"]["survived"]:
        out.append(f"  evidence: tests still pass when {m['file']}:{m['line']} `{m['from']}` is changed to `{m['to']}`")
    if not result["tests"]["passed"]:
        out.append("  evidence: the test run fails: " + " | ".join(result["tests"]["tail"][-2:]))
    if any(r["action"] == "send_back" for r in rows):
        out.append("Fix the work (or correct the claim), then submit the claims again.")
    for a in result["audits"]:
        out.append(f"AUDIT NEEDED for claim {a['index']}: spawn an `explore` subagent with this brief, then "
                   f"call submit_claims again with audit_notes {{\"{a['index']}\": <its findings>}}:\n{a['brief']}")
    return "\n".join(out)


def check_hook(store, text):
    """CLAIMS.md write (PreToolUse): block the write and show Bob the verdicts if anything is off."""
    result = verify(store, text, source="claims_file")
    return (0, "", "") if result["status"] == "accept" else (2, "", message(result))


def stop_hook(store, text):
    if text:
        result = verify(store, text, source="stop")
        if result["status"] != "accept":
            store.queue_note(message(result))
    from . import report as R
    R.write_hall_pass(store)
    return 0, "", ""


def report(result):
    out = ["# Receipts", "", "| Verdict | Action | Tier | Claim |", "|---|---|---|---|"]
    out += [f"| {r['verdict']} ({r['confidence']}) | {r['action']} | {r['tier']} | {r['claim']} |"
            for r in result["rows"]]
    t, s = result["tests"], result["sabotage"]
    out += ["", f"Tests: {'pass' if t['passed'] else 'FAIL'} (`{t['command']}`)",
            f"Sabotage: {s['killed']}/{s['mutants']} mutants killed"]
    out += [f"- survived: {m['file']}:{m['line']} `{m['from']}` -> `{m['to']}`" for m in s["survived"]]
    if result["risky_files"]:
        out += ["", "Deep review recommended: " + ", ".join(f"{f} (risk {x})" for f, x in result["risky_files"])]
    return "\n".join(out) + "\n"
