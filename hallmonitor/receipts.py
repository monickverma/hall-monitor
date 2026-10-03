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
A project rule that comes back "needs evidence" again on an unchanged diff goes to the user as a question, and
doesn't count as a send-back.

Entry points: the MCP tool submit_claims, a write to CLAIMS.md (PreToolUse; inline "[E12]" citations
count), and the Stop hook as a backstop.
"""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
import re
import time
from pathlib import Path
from . import fabricated as FB, mutation  # v4.2 fabricated files, extreme mutation

from . import bob, brief, evidence as EV, gitutil, jev, policy, questions as Q
from .store import is_protected

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
READ_CLAIM_RE = re.compile(r"^\s*(read|reviewed|inspected|extracted|opened|listed|checked|looked at|examined|parsed|"
                           r"scanned|searched|confirmed)\b", re.I)
CHANGE_VERB_RE = re.compile(r"\b(add|added|change|changed|modif\w+|updat\w+|wrote|writ\w+|creat\w+|remov\w+|delet\w+|"
                            r"fix\w*|implement\w*|edit\w*|replac\w+|refactor\w*|renam\w+|wired)\b", re.I)
SABOTAGE_KINDS = {"tests_added", "tests_pass", "implemented", "fixed", "obligation"}  # worth running sabotage
SHOW_SABOTAGE = {"tests_added", "obligation"}  # sabotage is about test quality; other claims aren't judged on it
JEV_TIERS = {"jev", "jev_deep", "jev+audit", "bob_shell_audit"}  # verdicts kept for a resubmission (verify)
MEMO_SKIP = {"index", "claim", "kind", "cited", "named", "detail"}
STATE_LABEL = {"verified": "VERIFIED", "contradicted": "CONTRADICTED", "needs_evidence": "NEEDS EVIDENCE",
               "cant_check": "CAN'T CHECK"}
FILE_RE = re.compile(r"[A-Za-z0-9_][\w./-]*\.[A-Za-z]{1,5}\b")
CITE_RE = re.compile(r"\bE\d+\b")


HEADER_TAG = "from the header:"
HEADER_TAG_RE = re.compile(r" \[from the header: [^\]]*\]$")
BULLET_RE = re.compile(r"^([-*\u2022]|\d+[.)])\s+")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
TABLE_ROW_RE = re.compile(r"^\|.*\|$")
TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}")
RULE_CELL_RE = re.compile(r"^(D\d+\b|rules?$)", re.I)


def _under_headers(text):
    """Free text with each list item tagged with the files and receipt IDs of the header it sits under.
    Real Bob, Sept 27: Bob grouped its claims under lines like "**[`README.md`](README.md)** — E1:". Each
    header was judged as a claim of its own, and the items below it came back uncited, or contradicted
    for naming only the files they point to. A line ending in ":" that introduces a list is not a claim."""
    lines = [x.strip() for x in (text or "").splitlines()]
    body = [x for x in lines if x]
    out, tag = [], ""
    for k, line in enumerate(body):
        nxt = body[k + 1] if k + 1 < len(body) else ""
        # A markdown table: real Bob, Sept 28, recapped its work as "| Rule | Status |" rows, and every row, header
        # included, came back needing evidence until a one-line docstring task was STUCK. Header and separator rows
        # aren't claims; a row about a rule (D2 ...) restates what Receipts checks itself; other rows are one claim.
        if TABLE_ROW_RE.match(line):
            cells = [c.strip(" *`") for c in line.strip().strip("|").split("|")]
            if TABLE_SEP_RE.match(line) or TABLE_SEP_RE.match(nxt) or RULE_CELL_RE.match(cells[0]):
                continue
            line = " - ".join(c for c in cells if c)
        if line.startswith("#") or line.endswith(":"):  # headings and introductions are never claims
            tag = ""
            if line.endswith(":") and (BULLET_RE.match(nxt) or nxt.endswith(":")):
                plain = re.sub(r"[*`]+", "", MD_LINK_RE.sub(r"\1", line))
                refs = list(dict.fromkeys(FILE_RE.findall(plain) + CITE_RE.findall(plain)))
                tag = f" [{HEADER_TAG} {' '.join(refs)}]" if refs else ""
            continue
        if BULLET_RE.match(line):
            line = BULLET_RE.sub("", line) + tag
        else:
            tag = ""
        out.append(line)
    return "\n".join(out)


def parse(claims_or_summary):
    """[(text, cited IDs)] from certificate objects {claim, evidence}, plain strings, or free text.
    Inline citations such as "[E12]" count, so a CLAIMS.md file can cite receipts too."""
    items = brief.sentences(_under_headers(claims_or_summary), limit=20) if isinstance(claims_or_summary, str) \
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


DECISION_RE = re.compile(r"\bD(\d+)(?:\s*[-\u2013]\s*D?(\d+))?\b")
# Only a claim that rules were *recorded* is about the ledger; "satisfies rule D3" is about the work.
RECORDED_RE = re.compile(r"\b(record(ed|s|ing)?|extract(ed|s|ing)?)\b", re.I)


def recorded_decisions(claim, decisions):
    """A claim that rules were recorded ("recorded them as decisions D1-D6") is checked against the rule
    ledger, in code. Returns None when the claim isn't about recorded decisions, else (state, code, detail).
    Real Bob, Sept 27: such a claim named the policy file and app/auth.py, and was contradicted because
    neither changed."""
    ids = []
    for a, b in DECISION_RE.findall(claim):
        ids += [f"D{n}" for n in range(int(a), int(b or a) + 1)] if int(b or a) - int(a) < 50 else []
    if not ids or not RECORDED_RE.search(claim):
        return None
    missing = [i for i in dict.fromkeys(ids) if i not in decisions]
    if missing:
        return "contradicted", "unknown", f"{', '.join(missing)} is not in the rule ledger."
    return "verified", "ledger", f"{', '.join(dict.fromkeys(ids))} are in the rule ledger."


FAILS_WITHOUT_RE = re.compile(r"\btests?\b.{0,60}\bfails?\b.{0,30}\bwithout\b.{0,20}\bchange", re.I)
# "Tests must assert on the specific changed behavior; tests that only exercise the happy path ... don't satisfy
# the testing requirement." Real Bob, Sept 27: Jev couldn't settle it from the diff, so it went to an audit in
# four of the subagent runs, and each audit cost Bob a round.
ASSERTS_CHANGE_RE = re.compile(r"\btests?\b.{0,60}\bassert\w*\b.{0,40}\bchang\w*\b.{0,20}\bbehavio", re.I)
CONDITIONAL_RE = re.compile(r"^\s*(any\s+)?(changes?|edits?|modifications?)\s+(to|of|in)\b"
                            r"|\b(if|when|whenever)\b.{0,80}\b(chang|edit|modif|touch)", re.I)


# What a scoped rule is about: the words before its "must" ("Password comparison must use a constant-time ...").
SUBJECT_RE = re.compile(r"^\s*([^.;:()]{1,80}?)\s+(must|should|shall|needs? to|ha(s|ve) to|(is|are) required)\b",
                        re.I)
# A subject made only of these words is about every change, so the rule always applies: "Every behavior change
# must ship with a test", "Tests must assert on the specific changed behavior", "New code must ...".
EVERY_CHANGE = set("""a an the all any each every new our your this that these those to of in on for with by and or
    behavior behaviour behaviors behaviours change changes changed code test tests testing work commit commits
    feature features function functions method methods class classes file files module modules pr prs patch
    patches edit edits fix fixes implementation implementations public api apis endpoint endpoints project
    repo repository program programs software finished final complete completed whole entire pull request
    requests merge merges release releases branch branches diff diffs message messages documentation docs doc
    readme changelog""".split())
COMMENT_RE = re.compile(r"(^|\s)#.*$|^\s*(//|/\*|\*).*$")  # `*` and `//` are Python operators mid-line
# A subject word that names something code does, by its stem, and what a line doing it looks like. Real Bob,
# Sept 27 (subagents, $2.03): the edit to login() touched lines that mention `password`, so "Password comparison
# must use a constant-time algorithm" applied, came back "needs evidence" three rounds running, and the task
# ended STUCK. That rule is about a line that compares something in code about passwords.
OPERATIONS = {"compar": re.compile(r"==|!=|compare|\beq\(|__eq__")}


def _stem(word):
    for suffix in ("isons", "ison", "ations", "ation", "ings", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def _text(root, path):
    try:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return ""


def untouched_subject(rule, changed, root=None):
    """The words of a scoped rule's subject when the change doesn't touch them, else None. Touched means a
    changed code line (added or removed, comments aside) or a changed code file's path mentions one of them.
    Real Bob, Sept 27: "Password comparison must use a constant-time algorithm" came back "needs evidence" on a
    rate-limit change with no password code, and Bob spent the rest of its cost cap answering it. A rule with no
    subject ("Do not add ...") or one about every change ("Every behavior change must ship with a test") always
    applies.
    A subject that names an operation (OPERATIONS: "comparison") is touched only by a changed line that does it,
    outside the tests (a test's `==` checks a result), and that names the subject itself or sits in a file whose
    path, changed lines or text under `root` mention the rest of it. So replacing
    `hmac.compare_digest(expected, given)` with `expected == given` in app/auth.py touches it, and a rate-limit
    line in login(user, password) doesn't."""
    m = SUBJECT_RE.match(rule)
    words = [_stem(w) for w in re.findall(r"[a-z]+", m[1].lower()) if w not in EVERY_CHANGE] if m else []
    if not words:
        return None
    lines = {f: [COMMENT_RE.sub("", t).lower() for t in [t for _, t in c["added"]] + list(c.get("removed_lines", []))]
             for f, c in changed.items() if not f.lower().endswith((".md", ".txt", ".rst", ".pdf"))}
    ops = [rx for k, rx in OPERATIONS.items() if any(w.startswith(k) for w in words)]
    if not ops:
        text = "\n".join([f.lower() for f in lines] + [t for ls in lines.values() for t in ls])
        return None if any(w in text for w in words) else m[1].strip()
    nouns = [w for w in words if not any(w.startswith(k) for k in OPERATIONS)]
    for f, ls in lines.items():
        doing = [] if gitutil.is_test(f) else [t for t in ls if all(rx.search(t) for rx in ops)]
        if not doing:
            continue
        about = "\n".join([f.lower(), *ls, _text(root, f) if root else ""])
        if not nouns or any(w in t for t in doing for w in words) or any(n in about for n in nouns):
            return None
    return m[1].strip()


def not_applicable(rule, files, changed, root=None):
    """A rule about changes to certain files ("Changes to app/auth.py require a security review") holds when
    none of them changed. Real Bob, Sept 27: that rule came back "needs evidence" every round of a task that
    never touched app/auth.py, until the task was STUCK. So does a rule about one kind of code that the change
    doesn't touch (untouched_subject). Returns None when the rule does apply."""
    if files and CONDITIONAL_RE.search(rule) and not any(f in changed for f in files):
        return "verified", "not_applicable", f"{', '.join(files)} didn't change, so this rule doesn't apply."
    subject = None if files else untouched_subject(rule, changed, root)
    if subject:
        return ("verified", "not_applicable",
                f"No changed code is about {subject.lower()}, so this rule doesn't apply to this change.")
    return None


def no_behavior_change(rule, root, base, changes_):
    """A rule about the tests a behavior change needs holds when no changed line outside the tests changes
    behavior: only docstrings, comments or blank lines changed (gitutil.behavior_lines). Returns None when the
    rule does apply."""
    if not base or not (FAILS_WITHOUT_RE.search(rule) or ASSERTS_CHANGE_RE.search(rule)):
        return None
    if gitutil.behavior_lines(root, base, changes_):
        return None
    return ("verified", "not_applicable", "No changed line outside the tests changes behavior (only docstrings, "
            "comments or blank lines), so this rule doesn't apply.")


def tests_catch_change(before, sab):
    """A rule that tests must assert on the changed behavior, decided on Hall Monitor's own evidence: the changed
    tests fail on the code before the change, and they catch at least one sabotage mutant of the changed lines.
    Failing on the old code alone isn't enough: a test that imports a new module fails there on the import,
    whatever it asserts. Returns None (go on to Jev) when there's no mutant to tell."""
    if before["on_code_before_change"] == "pass":
        return ("contradicted", "fail_before", "The changed tests pass on the code before the change "
                f"({', '.join(before['changed_tests'])}), so they don't assert on what changed.")
    if sab.get("killed"):
        return ("verified", "fail_before", f"The changed tests fail on the code before the change "
                f"({', '.join(before['changed_tests'])}) and catch {sab['killed']} of {sab['mutants']} sabotage "
                "mutants of the changed lines, so they assert on the changed behavior.")
    return None


def own_files(claims, known):
    """The files a submission's claims name: a subagent's part."""
    return {f for c in claims for f in named_files(c["claim"], known)}


def own_test_command(cmd, claims, known, root):
    """The test command for a subagent's round: pytest on the test files its claims name, or None (the whole
    suite) when they name none or the project doesn't use pytest."""
    tests = sorted(f for f in own_files(claims, known)
                   if gitutil.is_test(f) and f.endswith(".py") and (Path(root) / f).is_file())
    return f"{cmd} {' '.join(tests)}" if tests and "pytest" in cmd else None


def certify(kind, cited, named, changed, ledger, fresh, unknown=(), own=None):
    """The certificate check, in code. Returns None (go on to Jev) or (state, reason_code, detail).
    `unknown`: code files the claim names that exist nowhere in the repo (fabricated.unknown_files).
    `own`: in a subagent's round, the files its claim names; only their edits make its test run stale."""
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
        last_edit = EV.last_code_edit_seq(r for r in ledger.values() if own is None or r.get("file") in own)
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


def _excerpt(c, words, room):
    """A long file edit cut down to about `room` characters: the added lines that share the most words
    with the claim, then their neighbours, in file order; its first lines only if none share a word.
    Each gap is marked, so a cut is never read as an absence."""
    added = c["added"]
    score = [len(words & set(WORD_RE.findall(t.lower()))) for _, t in added]
    order = sorted((k for k, n in enumerate(score) if n), key=lambda k: (-score[k], k)) or list(range(len(added)))
    keep, used = set(), 0
    for k in order + [j for k in order for j in (k - 1, k + 1) if 0 <= j < len(added)]:
        size = len(added[k][1]) + 2
        if k not in keep and used + size <= room:
            keep.add(k)
            used += size
    rows, prev = [], -1
    for j in sorted(keep):
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
    key = {w for w in WORD_RE.findall(HEADER_TAG_RE.sub("", claim).lower()) if w not in STOPWORDS}
    long = [f for f, c in ordered.items() if len(c["added"]) > EXCERPT_OVER]
    short = sum(len(gitutil.diff_text({f: c}, budget)) for f, c in ordered.items() if f not in long)
    room = max(500, (budget - short) // max(1, len(long)) - 150)  # 150: the header and gap markers
    return gitutil.diff_text({f: _excerpt(c, key, room) if f in long else c for f, c in ordered.items()}, budget)


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


def verify(store, claims_or_summary, audit_notes=None, source="mcp", agent="main"):
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
    # .bob/ and .hallmonitor/ are Hall Monitor's own (installed after the base commit in a demo repo), and
    # Bob can't write them: real Bob, Sept 27, they were the only "code" in a docs task's diff.
    all_changes = {f: c for f, c in gitutil.changes(store.root, sess.get("base")).items()
                   if not is_protected(store.root, f)}
    # Obligations from the ledger are implicit claims: the finished work must satisfy them. With no work for them
    # to apply to, they're skipped: real Bob, Sept 27, a /decisions turn was asked to prove "Changes to
    # app/auth.py require a security review" and spent its cost cap trying. The work is an edit in the evidence
    # ledger or a change in the diff: a tool that leaves no edit receipt (a shell command that writes a file)
    # must not skip the rules (security audit, Oct 2).
    # A subagent's submission covers its part: the project's rules are about the finished work, so they're
    # checked on the main agent's. Real Bob, Sept 27: a tidy-up subagent's three submissions were held to every
    # rule and used up the task's send-backs before the main agent submitted.
    if agent == "main" and (all_changes or any(r.get("kind") == "edit" for r in store.evidence())):
        claims += [{"claim": f"The finished work satisfies the project rule {d['id']}: \"{d['text']}\"",
                    "kind": "obligation", "cited": [], "from": "ledger", "rule": d["text"]}
                   for d in store.active_decisions(kind="obligation")]
    # Audit notes count only for audits Hall Monitor requested in the last round, on the same claim.
    # Anything else is ignored, so attaching notes can't be used to skip a send-back round.
    requested = (sess.get("pending_audits") if agent == "main" else
                 (sess.get("agent_pending_audits") or {}).get(agent)) or {}
    offered ={int(k): v for k, v in (audit_notes or {}).items()}
    audit_notes = {i: v for i, v in offered.items()
                   if 0 <= i < len(claims) and requested.get(str(i)) == claims[i]["claim"]}
    resubmit = bool(audit_notes)  # the same round, completed with the requested audit

    docs = {cfg["claims_file"].lower()}
    changes = {f: c for f, c in all_changes.items()
               if f.lower() not in docs and not f.lower().endswith((".md", ".txt", ".rst", ".pdf"))}
    ledger = {r["id"]: r for r in store.evidence()}
    decisions = {d["id"] for d in store.ledger()}  # the rule ledger, for claims about recorded rules
    known = set(gitutil.tracked_files(store.root)) | set(all_changes) | \
        {r["file"] for r in ledger.values() if r.get("file")}
    free_retry = not sess["uncited_retry_used"]
    # A subagent's round checks its part; the main agent's final round checks the whole. So a subagent's fresh
    # test run (and sabotage) covers the test files its claims name, and its test run goes stale only when a file
    # its claim names changes after it. Real Bob, Sept 28 (subagents): two parallel subagents' rounds were held to
    # each other's work. One's claims came back "stale" after the other's later edit; the other's came back
    # "contradicted" because the full suite failed to collect the first one's half-written test file.
    cmd = own_test_command(cfg["test_command"], claims, known, store.root) if agent != "main" else None
    cmd = cmd or cfg["test_command"]
    tests = gitutil.run_tests(store.root, cmd)

    for c in claims:
        # A header's files tell where an item is; they aren't what a claim that something stayed the
        # same is about ("First line kept as ..." under a README.md header).
        said = HEADER_TAG_RE.sub("", c["claim"]) if c["kind"] == "unchanged" else c["claim"]
        # A claim that files were only read names them without saying they changed. Real Bob, Sept 28: "Read
        # docs/security-policy.pdf and extracted its text" was contradicted three rounds running as a diff mismatch.
        reading = READ_CLAIM_RE.match(said) and not CHANGE_VERB_RE.search(said)
        c["named"] = named_files(said, known) if c["from"] == "agent" and not reading else []
        # The diff Jev is shown. A rule's own files count too: real Bob, Sept 27, "The finished work satisfies
        # D1: Add a section to README.md" was judged on a diff without README.md and contradicted every round.
        c["where"] = named_files(c["claim"], known)
        about_rules = recorded_decisions(c["claim"], decisions) if c["from"] == "agent" else None
        if c["from"] == "ledger":
            about_rules = not_applicable(c["rule"], named_files(c["rule"], known), all_changes, store.root) or \
                no_behavior_change(c["rule"], store.root, sess.get("base"), changes)
        cert = about_rules if c["from"] == "ledger" else about_rules or \
            certify(c["kind"], c["cited"], c["named"], all_changes, ledger, tests,
                    FB.unknown_files(store.root, sess.get("base"), c["claim"], known),  # v4.2 fabricated files
                    own=c["named"] if agent != "main" and c["named"] else None)
        if cert and cert[1] == "uncited" and not free_retry:
            cert, c["uncited_fallback"] = None, True  # after the free retry: judged the old way, marked uncited
        c["cert"] = cert

    to_judge = [i for i, c in enumerate(claims) if c["cert"] is None]
    needs_sabotage = tests["passed"] and any(claims[i]["kind"] in SABOTAGE_KINDS for i in to_judge)
    mine = {f: ch for f, ch in changes.items() if f in own_files(claims, known)} if agent != "main" else {}
    sab = gitutil.sabotage(store.root, mine or changes, cmd, cfg["max_mutants"]) if needs_sabotage \
        else {"mutants": 0, "killed": 0, "survived": [], "note": "not run"}
    changed_files = {f: c["status"] for f, c in changes.items()}
    if needs_sabotage:  # v4.2 extreme mutation (mutation.py): pseudo-tested functions join the sabotage evidence
        sab = {**sab, **mutation.extreme(store.root, mine or changes, {**cfg, "test_command": cmd})}
        # Fail-before/pass-after: do the changed tests fail on the code as it was before the change?
        before = gitutil.fail_before(store.root, sess.get("base"), changes, cmd)
        if before:
            sab = {**sab, "tests_on_code_before_change": before}
            # A rule that tests must fail without the change is exactly this check, so code decides it.
            for i in [i for i in to_judge if FAILS_WITHOUT_RE.search(claims[i].get("rule") or "")]:
                ok = before["on_code_before_change"] == "fail"
                claims[i]["cert"] = ("verified" if ok else "contradicted", "fail_before",
                                     f"The changed tests {'fail' if ok else 'pass'} on the code before the change "
                                     f"({', '.join(before['changed_tests'])}).")
            for i in [i for i in to_judge if ASSERTS_CHANGE_RE.search(claims[i].get("rule") or "")]:
                claims[i]["cert"] = tests_catch_change(before, sab)
            to_judge = [i for i in to_judge if claims[i]["cert"] is None]

    # The same claim, with the same citations, on the same diff gets the same verdict as in an earlier round, so
    # resubmitting can't re-roll Jev, in either direction. Real Bob, Sept 27 (subagents, $2.51): "Added 7 new
    # tests in tests/test_service.py ..." was verified in one round and contradicted in the next with no edit in
    # between, and the rounds used up the cost cap. Claims that went to an audit or were refused aren't kept.
    diff_id = hashlib.sha1(json.dumps(all_changes, sort_keys=True).encode()).hexdigest()[:12]
    memo = sess.get("verdict_memo") or {}
    memo = memo if memo.get("diff") == diff_id else {"diff": diff_id, "rows": {}}
    memo_key = lambda i: hashlib.sha1(json.dumps(  # noqa: E731
        [" ".join(claims[i]["claim"].lower().split()), sorted(claims[i]["cited"]),
         bool(claims[i].get("uncited_fallback"))]).encode()).hexdigest()[:16]
    kept = {i: memo["rows"][memo_key(i)] for i in to_judge if i not in audit_notes and memo_key(i) in memo["rows"]}
    to_judge = [i for i in to_judge if i not in kept]

    def verdict_job(i, deep=False):
        c = claims[i]
        # A claim that names a changed doc is judged on that doc's diff. Real Bob, Sept 27: docs were left
        # out of every diff, so each claim about README.md met an empty one and came back "says nothing".
        scope = {f: ch for f, ch in all_changes.items() if f in c["where"] and f.lower() not in docs} or changes
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
    # The Bob Shell audits run in parallel within one time budget, so the round still answers Bob's submit_claims
    # call in time; an audit that runs out of time falls back to the explore subagent.
    audits = []
    deep = [i for i in answers if tiers[i] == "jev_deep" and decisions[i].escalate]
    briefs = {i: audit_brief(claims[i]["claim"], changed_files, tests, sab) for i in deep}
    with ThreadPoolExecutor(max_workers=max(len(deep), 1)) as pool:
        found = dict(zip(deep, pool.map(lambda i: bob.shell_audit(store.root, briefs[i],
                                                                  timeout=cfg["shell_audit_timeout"]), deep)))
    for i in deep:
        if found[i]:
            audit_notes[i] = found[i]
            try:
                a, u = jev.ask(*verdict_job(i, deep=True))
                answers[i], decisions[i], tiers[i] = a, judge(a, None), "bob_shell_audit"
                tok += jev.tokens(u)
            except jev.JevRefused:
                audits.append({"index": i, "claim": claims[i]["claim"], "brief": briefs[i]})
        else:
            audits.append({"index": i, "claim": claims[i]["claim"], "brief": briefs[i]})

    rows = []
    for i, c in enumerate(claims):
        base = {"index": i, "claim": c["claim"], "kind": c["kind"], "cited": c["cited"], "named": c["named"]}
        if c["cert"]:
            state, code, detail = c["cert"]
            rows.append({**base, "state": state, "code": code, "detail": detail, "verdict": state,
                         "confidence": 1.0, "tier": "code",
                         "action": "accept" if state == "verified" else "send_back"})
            continue
        if i in kept:
            rows.append({**base, **kept[i], "code": kept[i].get("code") or "same_as_before",
                         "detail": "Same claim, citations and diff as an earlier round, so the same verdict."})
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

    # A project rule that came back "needs evidence" last round, on this same diff, can't be settled by Bob
    # resubmitting: it goes to the user as a question, and doesn't use up a send-back. Real Bob, Sept 27
    # (subagents, $2.03): D2 came back "needs evidence" in three rounds, the last two on the same diff, and the
    # task ended STUCK.
    before = sess["rules_needing_evidence"]
    asked = [r for r in rows if claims[r["index"]]["from"] == "ledger" and r["state"] == "needs_evidence"
             and before.get(r["claim"]) == diff_id]
    for r in asked:
        r.update(state="cant_check", code="ask_user", action="audit",
                 detail="This rule came back \"needs evidence\" twice on the same diff, so resubmitting won't "
                        "settle it. Ask the user whether the finished work satisfies it.")

    bad = [r for r in rows if r["action"] == "send_back"]
    free = bool(bad) and free_retry and all(r["code"] == "uncited" and r["tier"] == "code" for r in bad)
    status = "needs_evidence" if free else "send_back" if bad else "audit" if audits or refused or asked else "accept"

    sess = store.session()
    if agent == "main":  # the project's rules are checked on the main agent's rounds only
        sess["rules_needing_evidence"] = {r["claim"]: diff_id for r in rows if claims[r["index"]]["from"] == "ledger"
                                          and (r["state"] == "needs_evidence" or r["code"] == "ask_user")}
    memo["rows"].update({memo_key(r["index"]): {k: v for k, v in r.items() if k not in MEMO_SKIP}
                         for r in rows if r["tier"] in JEV_TIERS and r["state"] != "cant_check"})
    sess["verdict_memo"] = memo
    if free:
        sess["uncited_retry_used"] = True
    # Each subagent has its own send-back count; the task's (main's) count is sess["send_backs"].
    counts = sess.setdefault("agent_send_backs", {})
    count = sess["send_backs"] if agent == "main" else counts.get(agent, 0)
    if resubmit:  # finishing the same round with an audit is not a new send-back
        if status == "accept":
            count, sess["last_send_back"] = 0, None
    else:
        count, status = next_round(count, status, cfg["max_send_backs"])
        if status in ("send_back", "stuck"):
            sig = sorted(f"{r['claim'][:80]}|{r['state']}|{r['code']}" for r in bad)
            if sig == sess["last_send_back"]:
                EV.stall(store, sess, "repeating a rejected approach",
                         "the same claims came back for the same reasons")
            sess["last_send_back"] = sig
        elif status == "accept":
            sess["last_send_back"] = None
    # The audits requested this round; only notes for these (same index, same claim) count next time.
    # Kept per agent: a subagent's round must not replace the main agent's audits (audit sweep, Sept 28).
    requested_now = {str(a["index"]): a["claim"] for a in audits}
    if agent == "main":
        sess["pending_audits"] = requested_now
    else:
        sess.setdefault("agent_pending_audits", {})[agent] = requested_now
    sess.setdefault("audit_briefs", {})[agent] = [a["brief"] for a in audits]  # step.requested_audit matches these
    if agent == "main":
        sess["send_backs"] = count
    else:
        counts[agent] = count
    if status == "accept" and agent == "main":  # the Stop backstop leaves work verified up to here alone
        sess["verified_edit_seq"] = sess["edit_seq"]
    # v4 loop L4 -> L1: the files a contradicted claim names are suspect, so the next intent or edit that
    # touches them gets the deep look straight away. A verified round clears them.
    # Only the main agent's verified round clears them: a subagent's accepted round covers its own part only.
    suspect = {f: r["claim"][:160] for r in rows if r["state"] == "contradicted"
               for f in (claims[r["index"]].get("where") or [])}
    sess["suspect_files"] = {} if status == "accept" and agent == "main" else {**sess.get("suspect_files", {}), **suspect}
    store.save_session(sess)

    cps = EV.checkpoints(store.evidence())
    result = {"rows": rows, "tests": tests, "sabotage": sab, "risky_files": risky, "audits": audits,
              "status": status, "send_backs": sess["send_backs"], "checkpoint": cps[-1] if cps else None}
    store.write_report("receipts.md", report(result))
    store.write_report("receipts.json", json.dumps(result, indent=2))
    store.log({"stage": "receipts", "source": source, "agent": agent, "claims": len(rows), "action": status,
               "verdicts": {r["claim"][:80]: r["state"] for r in rows},
               "codes": {r["claim"][:80]: r["code"] for r in rows if r["code"]},
               "tiers": [r["tier"] for r in rows], "risky_files": risky, "send_backs": sess["send_backs"],
               "ignored_audit_notes": len(offered) - len(audit_notes) or None,
               "mutants": sab["mutants"], "survived": len(sab["survived"]),
               "tokens": tok, "ms": int((time.time() - t0) * 1000)})
    return result


def task_rounds(events):
    """The task's Receipts rounds: the main agent's. A subagent's accepted round covers its part, not the task.
    Real Bob, Sept 27: a tidy-up subagent's verified docstrings made a task look verified while the main
    agent never submitted its own claims. (Rounds logged before agents were recorded count as the main's.)"""
    return [e for e in events if e.get("stage") == "receipts" and e.get("agent") in (None, "main")]


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
            "audit": "Receipts: some claims need an independent audit." if result["audits"] else
                     "Receipts: some claims need the user's answer.",
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
    fb = s.get("tests_on_code_before_change")
    if fb:  # fail-before/pass-after
        out.append(f"Changed tests on the code before the change: {fb['on_code_before_change'].upper()}"
                   + (" (good: they check the change)" if fb["on_code_before_change"] == "fail"
                      else " (they pass without the change, so they don't check it)"))
    if result.get("checkpoint"):
        cp = result["checkpoint"]
        out += ["", f"Last checkpoint: {cp['checkpoint']} (`{cp['ref']}`, from {cp['from']})"]
    if result["risky_files"]:
        out += ["", "Riskiest changed files: " + ", ".join(f"{f} (risk {x})" for f, x in result["risky_files"])]
    return "\n".join(out) + "\n"
