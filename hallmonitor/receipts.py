"""AFTER: Receipts. Every claim Bob makes about its work is checked against evidence.

Claims carry receipts. Bob calls list_evidence and cites the IDs (E1, E2, ...) of the recorded edits
and test runs that prove each claim. Code checks that certificate before Jev is asked:
- the files a claim names must be in the diff (or, for "X was not modified", must not be);
- every cited receipt must exist;
- a cited test run must have passed;
- the receipts must be about what the claim is about;
- test runs must be newer than the last code edit;
- the fresh test run must agree.
A failed check gives a reason code and a verdict (needs evidence, or contradicted) without Jev.

Certified claims go on to sabotage and Jev, which sees only the cited receipts, the fresh test run,
the sabotage results and the diff of the files the claim names, never Bob's summary. A claim is only
sent back as false when the verdict and a separate "does the evidence show it's false?" question agree.
If they disagree, the claim gets a closer look.

Four states: verified, contradicted, needs evidence, can't check.

Escalation for a claim Jev judges: Jev on the cited evidence -> Jev deep look on all evidence -> a
read-only Bob `explore` subagent audits the code -> Jev judges again with that audit -> the user.

Stop rule: at most `max_send_backs` send-backs. The next one makes the task stuck, and Receipts names
the checkpoint to restore. Hall Monitor never rolls back by itself. An uncited claim gets one free
retry that doesn't count; after that, uncited claims are judged the old way and marked uncited.

Entry points: the MCP tool submit_claims, a write to CLAIMS.md (PreToolUse; inline "[E12]" citations
count), and the Stop hook as a backstop.
"""
import json
import re
import time
from . import fabricated as FB, mutation  # v4.2 fabricated files, extreme mutation

from . import bob, brief, evidence as EV, gitutil, jev, policy, questions as Q

# Evidence for claims judged without citations (after the free retry, and Hall Monitor's own
# obligation claims), per claim kind (less noise, fewer tokens).
EVIDENCE_FOR = {
    "implemented": ("changed_files", "diff"),
    "fixed": ("changed_files", "diff", "tests"),
    "unchanged": ("changed_files",),
    "tests_added": ("changed_files", "diff", "tests", "sabotage"),
    "tests_pass": ("tests", "commands_the_agent_ran"),
    "other_claim": ("changed_files", "diff"),
    "obligation": ("changed_files", "diff", "tests", "sabotage"),
}
TEST_KINDS = {"tests_pass", "tests_added", "fixed"}
CHANGE_KINDS = {"implemented", "fixed", "tests_added", "other_claim"}
SABOTAGE_KINDS = {"tests_added", "tests_pass", "implemented", "fixed", "obligation"}  # worth running sabotage
SHOW_SABOTAGE = {"tests_added", "obligation"}  # sabotage is about test quality; other claims aren't judged on it
STATE_LABEL = {"verified": "VERIFIED", "contradicted": "CONTRADICTED", "needs_evidence": "NEEDS EVIDENCE",
               "cant_check": "CAN'T CHECK"}
FILE_RE = re.compile(r"[A-Za-z0-9_][\w./-]*\.[A-Za-z]{1,5}\b")
CITE_RE = re.compile(r"\bE\d+\b")


def parse(claims_or_summary):
    """[(text, cited IDs)] from certificate objects {claim, evidence}, plain strings, or free text.
    Inline citations such as "[E12]" count, so a CLAIMS.md file can cite receipts too."""
    items = brief.sentences(claims_or_summary, limit=20) if isinstance(claims_or_summary, str) \
        else list(claims_or_summary or [])
    out = []
    for c in items:
        if isinstance(c, dict):
            text = str(c.get("claim") or c.get("text") or "").strip()
            ids = [str(x).strip().upper() for x in (c.get("evidence") or c.get("receipts") or []) if str(x).strip()]
        else:
            text = str(c).strip()
            ids = CITE_RE.findall(text)
        if text:
            out.append((text, list(dict.fromkeys(ids))))
    return out


def named_files(claim, known):
    """Files a claim names (a path or a file name), matched against files the repository knows."""
    toks = {t.lower().rstrip(".") for t in FILE_RE.findall(claim)}
    return sorted(f for f in known if f.lower() in toks or f.lower().rsplit("/", 1)[-1] in toks)


def certify(kind, cited, named, changed, ledger, fresh, unknown=()):
    """The certificate check, in code. Returns None (go on to Jev) or (state, reason_code, detail).
    `unknown`: code files the claim names that exist nowhere in the repo (fabricated.unknown_files)."""
    if unknown and kind in CHANGE_KINDS:  # v4.2: a claim about a file that doesn't exist is false, however cited
        return "contradicted", "unknown_file", FB.message(unknown)
    # What the claim itself says about files is decided first: a claim that files changed when none of
    # them did (or that a file wasn't touched when it was) is contradicted however it is cited.
    if named:
        hit = [f for f in named if f in changed]
        if kind == "unchanged":
            if hit:
                return "contradicted", "diff_mismatch", f"{', '.join(hit)} is in the diff."
            return "verified", "code", f"{', '.join(named)} is not in the diff."
        if kind in CHANGE_KINDS and not hit:
            return "contradicted", "diff_mismatch", f"None of the files this claim names ({', '.join(named)}) changed."
    if kind == "unchanged":
        return None  # nothing to cite for an absence; Jev judges it on the changed files
    if not cited:
        return "needs_evidence", "uncited", "Call list_evidence and resubmit this claim with the IDs that prove it."
    unknown = [i for i in cited if i not in ledger]
    if unknown:
        return "contradicted", "unknown", f"{', '.join(unknown)} does not exist in the evidence ledger."
    rows = [ledger[i] for i in cited]
    tests = sorted((r for r in rows if r["kind"] == "test"), key=lambda r: int(r["id"][1:]))
    if kind in TEST_KINDS and tests and tests[-1]["status"] == "fail":
        return "contradicted", "failed", f"{tests[-1]['id']} is a failing test run: {EV.last_line(tests[-1]['tail'])}"
    if kind in TEST_KINDS and not tests:
        return "needs_evidence", "out_of_scope", "Cite a test run (see list_evidence) made after your last edit."
    if named and not tests and not any(r.get("file") in named for r in rows):
        return ("needs_evidence", "out_of_scope",
                f"None of {', '.join(cited)} touches {', '.join(named)}. Cite the receipts for those files.")
    if tests:
        last_edit = EV.last_code_edit_seq(ledger.values())
        if tests[-1]["edit_seq"] < last_edit:
            return ("needs_evidence", "stale", f"{tests[-1]['id']} ran before your last code edit (#{last_edit}). "
                    "Re-run the tests and cite the new run.")
        if tests[-1]["status"] == "pass" and not fresh["passed"]:
            return ("contradicted", "replay_mismatch", f"{tests[-1]['id']} passed, but a fresh run of "
                    f"`{fresh['command']}` fails: {' | '.join(fresh['tail'][-2:])}")
    return None


def next_round(send_backs, status, limit):
    """Count send-back rounds: a verified round resets the count; past `limit` the task is stuck."""
    if status == "accept":
        return 0, status
    if status == "send_back":
        send_backs += 1
        return send_backs, ("stuck" if send_backs > limit else status)
    return send_backs, status


# How much diff Jev sees per claim. Real Bob, Sept 27: at 2,500 characters (and 60 lines per file in
# gitutil.diff_text) true claims about a long doc edit came back "says nothing", and the docs task ended
# STUCK. When a diff is still too long, _relevant_diff shows the lines the claim is about. The seeded eval
# never cuts a diff (its largest is 1,816 characters), so tests/test_evidence.py pins this with a long
# edit. A deep look at 12,000 gave 3 "can't check" verdicts.
FOCUSED_DIFF_BUDGET = 6000
DEEP_DIFF_BUDGET = 7000


WORD_RE = re.compile(r"[a-z_][a-z0-9_]{3,}")
STOPWORDS = {"that", "this", "with", "from", "into", "each", "every", "when", "then", "than", "have", "been",
             "were", "which", "there", "their", "they", "them", "what", "also", "only", "more", "must", "does",
             "done", "made", "added", "adds", "updated", "changed", "file", "files", "line", "lines", "now",
             "section", "sections", "should", "will", "would", "about", "after", "before", "under", "over"}
EXCERPT_OVER = 20  # a file with more added lines than this is excerpted when the diff doesn't fit


def _excerpt(c, words, context=1, max_hits=40):
    """A long file edit cut down to the added lines that share words with the claim (a line of context
    either side), after its first lines. Each gap is marked, so a cut is never read as an absence."""
    added = c["added"]
    score = [len(words & set(WORD_RE.findall(t.lower()))) for _, t in added]
    hits = [k for k, n in enumerate(score) if n]
    if len(hits) > max_hits:  # common words: keep the lines that share the most
        floor = sorted((score[k] for k in hits), reverse=True)[max_hits - 1]
        hits = [k for k in hits if score[k] >= floor][:max_hits]
    keep = sorted(set(range(min(5, len(added))))
                  | {j for k in hits for j in range(k - context, k + context + 1) if 0 <= j < len(added)})
    rows, prev = [], -1
    for j in keep:
        if j > prev + 1:
            rows.append((None, f"[... {j - prev - 1} added lines not shown]"))
        rows.append(added[j])
        prev = j
    if prev < len(added) - 1:
        rows.append((None, f"[... {len(added) - 1 - prev} added lines not shown]"))
    return {**c, "added": rows, "total_added": len(added)}


def _relevant_diff(changes, claim, budget=FOCUSED_DIFF_BUDGET):
    """Put files the claim mentions first, so the evidence the claim is about survives truncation. When
    the diff still doesn't fit, show the lines of each long edit that the claim is about (real Bob, Sept 27:
    a true claim about a README section 100 lines down came back "says nothing")."""
    words = set(re.findall(r"[A-Za-z_][\w./]*", claim.lower()))

    def mentioned(path):
        stem = path.lower().rsplit("/", 1)[-1]
        return path.lower() in words or stem in words or stem.split(".")[0] in words
    ordered = dict(sorted(changes.items(), key=lambda kv: not mentioned(kv[0])))
    text = gitutil.diff_text(ordered, budget)
    if "not shown]" not in text:
        return text
    key = {w for w in WORD_RE.findall(claim.lower()) if w not in STOPWORDS}
    return gitutil.diff_text({f: _excerpt(c, key) if len(c["added"]) > EXCERPT_OVER else c
                              for f, c in ordered.items()}, budget)


def _receipt_view(r):
    v = {k: r[k] for k in ("id", "kind", "file", "command", "status", "edit_seq", "checkpoint") if k in r}
    if r.get("tail"):
        v["output_tail"] = r["tail"][-400:]
    return v


def kind_by_code(text):
    """A claim's kind from its wording, used when Jev can't classify it (a refused request)."""
    for kind, pattern in KIND_RULES:
        if re.search(pattern, text, re.I):
            return kind
    return "other_claim"


KIND_RULES = [
    ("unchanged", r"\b(not|never)\b.{0,40}\b(modif|chang|touch|edit)|\b(unchanged|untouched|left alone)\b"),
    ("tests_pass", r"\b(all )?tests? (now )?pass|\bsuite passes\b"),
    ("tests_added", r"\b(added|wrote|new)\b.{0,40}\btests?\b|\btests? (that )?(verify|check|cover)"),
    ("fixed", r"\bfix(ed|es)?\b"),
    ("implemented", r"\b(implement|add|wire|creat|introduc|wrote|built)\w*"),
]


def verify(store, claims_or_summary, audit_notes=None, source="mcp"):
    t0 = time.time()
    cfg, sess = store.config(), store.session()
    parsed = parse(claims_or_summary)
    tok = 0
    claims = []
    if parsed:
        try:  # claim kinds come from Jev; if Jev refuses, from code, so the code checks below still decide
            kinds, usage = jev.ask({"sentences": [t for t, _ in parsed]},
                                   {f"kind_{i}": Q.claim_kind(i) for i in range(len(parsed))})
            tok += jev.tokens(usage)
            kind_of = lambda i: kinds[f"kind_{i}"]["choice"]  # noqa: E731
        except jev.JevRefused:
            kind_of = lambda i: kind_by_code(parsed[i][0])  # noqa: E731
        for i, (text, cited) in enumerate(parsed):
            kind = kind_of(i)
            if kind == "not_a_claim" and isinstance(claims_or_summary, str):
                continue
            claims.append({"claim": text, "kind": kind, "cited": cited, "from": "agent"})
    # Obligations from the ledger are implicit claims: the finished work must satisfy them.
    claims += [{"claim": f"The finished work satisfies the project rule {d['id']}: \"{d['text']}\"",
                "kind": "obligation", "cited": [], "from": "ledger"}
               for d in store.active_decisions(kind="obligation")]
    # Audit notes count only for audits Hall Monitor requested in the last round, on the same claim.
    # Anything else is ignored, so attaching notes can't be used to skip a send-back round.
    requested = sess.get("pending_audits") or {}
    offered = {int(k): v for k, v in (audit_notes or {}).items()}
    audit_notes = {i: v for i, v in offered.items()
                   if 0 <= i < len(claims) and requested.get(str(i)) == claims[i]["claim"]}
    resubmit = bool(audit_notes)  # the same round, completed with the requested audit

    all_changes = gitutil.changes(store.root, sess.get("base"))
    docs = {cfg["claims_file"].lower()}
    changes = {f: c for f, c in all_changes.items()
               if f.lower() not in docs and not f.lower().endswith((".md", ".txt", ".rst", ".pdf"))}
    tests = gitutil.run_tests(store.root, cfg["test_command"])
    ledger = {r["id"]: r for r in store.evidence()}
    known = set(gitutil.tracked_files(store.root)) | set(all_changes) | \
        {r["file"] for r in ledger.values() if r.get("file")}
    free_retry = not sess["uncited_retry_used"]

    for c in claims:
        c["named"] = named_files(c["claim"], known) if c["from"] == "agent" else []
        cert = None if c["from"] == "ledger" else \
            certify(c["kind"], c["cited"], c["named"], all_changes, ledger, tests,
                    FB.unknown_files(store.root, sess.get("base"), c["claim"], known))  # v4.2 fabricated files
        if cert and cert[1] == "uncited" and not free_retry:
            cert, c["uncited_fallback"] = None, True  # after the free retry: judged the old way, marked uncited
        c["cert"] = cert

    to_judge = [i for i, c in enumerate(claims) if c["cert"] is None]
    needs_sabotage = tests["passed"] and any(claims[i]["kind"] in SABOTAGE_KINDS for i in to_judge)
    sab = gitutil.sabotage(store.root, changes, cfg["test_command"], cfg["max_mutants"]) if needs_sabotage \
        else {"mutants": 0, "killed": 0, "survived": [], "note": "not run"}
    changed_files = {f: c["status"] for f, c in changes.items()}
    if needs_sabotage:  # v4.2 extreme mutation (mutation.py): pseudo-tested functions join the sabotage evidence
        sab = {**sab, **mutation.extreme(store.root, changes, cfg)}

    def verdict_job(i, deep=False):
        c = claims[i]
        scope = {f: ch for f, ch in changes.items() if f in c["named"]} or changes
        diff = _relevant_diff(scope, c["claim"], DEEP_DIFF_BUDGET if deep else FOCUSED_DIFF_BUDGET)
        if c["cited"] and not c.get("uncited_fallback"):
            ev = {"cited_receipts": [_receipt_view(ledger[x]) for x in c["cited"]],
                  "fresh_test_run": tests, "diff": diff}
            if deep or c["kind"] in SHOW_SABOTAGE:
                ev["sabotage"] = sab
        else:
            full = {"changed_files": changed_files, "diff": diff, "tests": tests, "sabotage": sab,
                    "commands_the_agent_ran": [x["command"] for x in sess.get("commands", [])]}
            ev = {k: full[k] for k in (list(full) if deep else EVIDENCE_FOR.get(c["kind"], full))}
        if i in audit_notes:
            ev["independent_audit"] = audit_notes[i][:3000]
        return {"claim": c["claim"], "claim_kind": c["kind"], "evidence": ev}, \
            {"verdict": Q.VERDICT, "false": Q.SHOWS_FALSE}

    def judge(ans, cost):
        dist = ans["verdict"]["probabilities"]
        worlds, reveal = policy.exclusive(dist, "supports")
        d = policy.decide(worlds, reveal, policy.CLAIM_HARM, escalate_cost=cost, risks=dist)
        if cost is not None and d.action == "send_back" and ans["verdict"]["choice"] == "contradicts" \
                and ans["false"]["noul"] < 0.5:
            d.escalate = True  # the two readings disagree: look closer before calling the claim false
        return d

    risk_jobs = [({"change": {"file": f, "status": c["status"],
                              "added": "\n".join(t for _, t in c["added"][:40])}}, {"risk": Q.FILE_RISK})
                 for f, c in changes.items()]
    results = jev.ask_many([verdict_job(i, deep=i in audit_notes) for i in to_judge] + risk_jobs,
                           return_refusals=True)
    ok = lambda r: not isinstance(r, jev.JevRefused)  # noqa: E731
    answers = {i: r[0] for i, r in zip(to_judge, results) if ok(r)}
    refused = [i for i in to_judge if i not in answers]  # these claims become "can't check"
    tok += sum(jev.tokens(r[1]) for r in results if ok(r))
    decisions = {i: judge(answers[i], cfg["claim_escalate_cost"]) for i in answers}
    tiers = {i: "jev+audit" if i in audit_notes else "jev" for i in answers}

    # Tier 2: a deep look, with all evidence and a longer diff, only where it could change the outcome.
    redo = [i for i in answers if decisions[i].escalate and i not in audit_notes]
    for i, r in zip(redo, jev.ask_many([verdict_job(i, deep=True) for i in redo], return_refusals=True)):
        if ok(r):  # a refused deep look keeps the focused answer
            answers[i], decisions[i], tiers[i] = r[0], judge(r[0], cfg["bob_audit_cost"]), "jev_deep"
            tok += jev.tokens(r[1])

    # Tier 3: still worth more scrutiny -> an independent Bob audit (Bob Shell if installed, else ask
    # the supervised Bob to spawn a read-only explore subagent and resubmit with its findings).
    audits = []
    for i in list(answers):
        if tiers[i] == "jev_deep" and decisions[i].escalate:
            brief_text = audit_brief(claims[i]["claim"], changed_files, tests, sab)
            notes = bob.shell_audit(store.root, brief_text)
            if notes:
                audit_notes[i] = notes
                try:
                    a, u = jev.ask(*verdict_job(i, deep=True))
                    answers[i], decisions[i], tiers[i] = a, judge(a, None), "bob_shell_audit"
                    tok += jev.tokens(u)
                except jev.JevRefused:
                    audits.append({"index": i, "claim": claims[i]["claim"], "brief": brief_text})
            else:
                audits.append({"index": i, "claim": claims[i]["claim"], "brief": brief_text})

    rows = []
    for i, c in enumerate(claims):
        base = {"index": i, "claim": c["claim"], "kind": c["kind"], "cited": c["cited"], "named": c["named"]}
        if c["cert"]:
            state, code, detail = c["cert"]
            rows.append({**base, "state": state, "code": code, "detail": detail, "verdict": state,
                         "confidence": 1.0, "tier": "code",
                         "action": "accept" if state == "verified" else "send_back"})
            continue
        if i in refused:
            rows.append({**base, "state": "cant_check", "code": "jev_refused", "action": "audit", "tier": "refused",
                         "verdict": "cant_check", "confidence": 0.0,
                         "detail": "Hall Monitor couldn't check this claim. Ask the user to review it."})
            continue
        a, d = answers[i], decisions[i]
        if any(x["index"] == i for x in audits):
            state, action = "cant_check", "audit"
        elif d.action in ("accept", "flag"):
            state, action = "verified", d.action
        else:
            state, action = ("contradicted" if a["verdict"]["choice"] == "contradicts" else "needs_evidence"), \
                "send_back"
        rows.append({**base, **d.as_dict(), "state": state, "action": action,
                     "code": "uncited" if c.get("uncited_fallback") else None, "detail": "",
                     "verdict": a["verdict"]["choice"], "confidence": round(a["verdict"]["confidence"], 2),
                     "shows_false": round(a["false"]["noul"], 2), "tier": tiers[i]})
    risky = [(st["change"]["file"], round(r[0]["risk"]["score"], 2))
             for (st, _), r in zip(risk_jobs, results[len(to_judge):]) if ok(r) and r[0]["risk"]["score"] >= 2.2]

    bad = [r for r in rows if r["action"] == "send_back"]
    free = bool(bad) and free_retry and all(r["code"] == "uncited" and r["tier"] == "code" for r in bad)
    status = "needs_evidence" if free else "send_back" if bad else "audit" if audits or refused else "accept"

    sess = store.session()
    if free:
        sess["uncited_retry_used"] = True
    if resubmit:  # finishing the same round with an audit is not a new send-back
        if status == "accept":
            sess["send_backs"], sess["last_send_back"] = 0, None
    else:
        sess["send_backs"], status = next_round(sess["send_backs"], status, cfg["max_send_backs"])
        if status in ("send_back", "stuck"):
            sig = sorted(f"{r['claim'][:80]}|{r['state']}|{r['code']}" for r in bad)
            if sig == sess["last_send_back"]:
                EV.stall(store, sess, "repeating a rejected approach",
                         "the same claims came back for the same reasons")
            sess["last_send_back"] = sig
        elif status == "accept":
            sess["last_send_back"] = None
    # The audits requested this round; only notes for these (same index, same claim) count next time.
    sess["pending_audits"] = {str(a["index"]): a["claim"] for a in audits}
    if status == "accept":  # the Stop backstop leaves work verified up to here alone (see stop_hook)
        sess["verified_edit_seq"] = sess["edit_seq"]
    store.save_session(sess)

    cps = EV.checkpoints(store.evidence())
    result = {"rows": rows, "tests": tests, "sabotage": sab, "risky_files": risky, "audits": audits,
              "status": status, "send_backs": sess["send_backs"], "checkpoint": cps[-1] if cps else None}
    store.write_report("receipts.md", report(result))
    store.write_report("receipts.json", json.dumps(result, indent=2))
    store.log({"stage": "receipts", "source": source, "claims": len(rows), "action": status,
               "verdicts": {r["claim"][:80]: r["state"] for r in rows},
               "codes": {r["claim"][:80]: r["code"] for r in rows if r["code"]},
               "tiers": [r["tier"] for r in rows], "risky_files": risky, "send_backs": sess["send_backs"],
               "ignored_audit_notes": len(offered) - len(audit_notes) or None,
               "mutants": sab["mutants"], "survived": len(sab["survived"]),
               "tokens": tok, "ms": int((time.time() - t0) * 1000)})
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


def restore_advice(cp):
    if cp:
        return (f"To go back to the last passing state, the user can restore checkpoint {cp['checkpoint']} "
                f"(made from passing test run {cp['from']}): `git stash push -u -m hm-before-restore`, then "
                f"`git checkout {cp['ref']} -- .`. Bob's own rollback also works. Hall Monitor never rolls "
                "back by itself.")
    return ("No passing checkpoint exists yet. The user can use Bob's rollback to return to the turn before the "
            "first edit of these files. Hall Monitor never rolls back by itself.")


def message(result):
    """What Bob sees: the state of every claim that isn't verified, with its reason and evidence."""
    rows, status, sab = result["rows"], result["status"], result["sabotage"]
    if status == "accept":
        out = [f"Receipts: all {len(rows)} claims verified. Tests pass; "
               f"{sab['killed']}/{sab['mutants']} sabotage mutants were caught."]
        if result["risky_files"]:
            out.append("Riskiest changed files, worth the user's own look: " +
                       ", ".join(f for f, _ in result["risky_files"]))
        out += [f"Also worth the user's look: {x}" for x in mutation.lines(sab)]  # v4.2 extreme mutation
        return "\n".join(out)
    out = [{"send_back": "Receipts: some claims are not backed by the evidence.",
            "needs_evidence": "Receipts: some claims don't cite their receipts yet. "
                              "This round doesn't count as a send-back.",
            "audit": "Receipts: some claims need an independent audit.",
            "stuck": f"Receipts: STUCK. Claims have now been sent back {result['send_backs']} times. "
                     "Stop repairing and tell the user:"}[status]]
    for r in rows:
        if r["state"] != "verified":
            code = f", {r['code']}" if r.get("code") else ""
            cited = f" [cites {', '.join(r['cited'])}]" if r["cited"] else ""
            out.append(f"- [{STATE_LABEL[r['state']]}{code}] {r['claim']}{cited}")
            if r.get("detail"):
                out.append(f"  {r['detail']}")
    for m in sab["survived"]:
        out.append(f"  evidence: tests still pass when {m['file']}:{m['line']} `{m['from']}` is changed to `{m['to']}`")
    out += [f"  evidence: {x}" for x in mutation.lines(sab)]  # v4.2 extreme mutation
    if not result["tests"]["passed"]:
        out.append("  evidence: the fresh test run fails: " + " | ".join(result["tests"]["tail"][-2:]))
    if status == "send_back":
        out.append("Fix the work (or correct the claim). Then call list_evidence and submit the claims again, "
                   "citing fresh receipts.")
    elif status == "needs_evidence":
        out.append("Call list_evidence, then resubmit each claim with the IDs of the receipts that prove it.")
    elif status == "stuck":
        out.append(restore_advice(result.get("checkpoint")))
    for a in result["audits"]:
        out.append(f"AUDIT NEEDED for claim {a['index']}: spawn an `explore` subagent with this brief, then "
                   f"call submit_claims again with audit_notes {{\"{a['index']}\": <its findings>}}:\n{a['brief']}")
    return "\n".join(out)


def check_hook(store, text):
    """CLAIMS.md write (PreToolUse): block the write and show Bob the verdicts if anything is off."""
    result = verify(store, text, source="claims_file")
    return (0, "", "") if result["status"] == "accept" else (2, "", message(result))


def stop_hook(store, text):
    """The backstop for work Bob finishes without submitting claims. Bob's last message is in the Stop
    payload (probe, Sept 27), but every turn ends in a Stop: judging a recap of verified work, or a turn
    with no edits (/decisions), put its uncited sentences over a VERIFIED result (preflight, Sept 27) and
    spent the free retry. So only edits no accepted submission covers make the message a claim."""
    sess = store.session()
    if text and sess["edit_seq"] > sess["verified_edit_seq"]:
        result = verify(store, text, source="stop")
        if result["status"] != "accept":
            store.queue_note(message(result))
    from . import report as R
    R.write_hall_pass(store)
    return 0, "", ""


def report(result):
    out = ["# Receipts", "", f"Status: **{result['status']}** (send-backs so far: {result['send_backs']})", "",
           "| State | Reason | Judged by | Cites | Claim |", "|---|---|---|---|---|"]
    out += [f"| {STATE_LABEL[r['state']]} | {r.get('code') or ''} | {r['tier']} | {', '.join(r['cited'])} "
            f"| {r['claim']} |" for r in result["rows"]]
    t, s = result["tests"], result["sabotage"]
    out += ["", f"Fresh test run: {'pass' if t['passed'] else 'FAIL'} (`{t['command']}`)",
            f"Sabotage: {s['killed']}/{s['mutants']} mutants killed"]
    out += [f"- survived: {m['file']}:{m['line']} `{m['from']}` -> `{m['to']}`" for m in s["survived"]]
    out += [f"- {x}" for x in mutation.lines(s)]  # v4.2 extreme mutation
    if result.get("checkpoint"):
        cp = result["checkpoint"]
        out += ["", f"Last checkpoint: {cp['checkpoint']} (`{cp['ref']}`, from {cp['from']})"]
    if result["risky_files"]:
        out += ["", "Riskiest changed files: " + ", ".join(f"{f} (risk {x})" for f, x in result["risky_files"])]
    return "\n".join(out) + "\n"
