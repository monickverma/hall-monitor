"""BEFORE: certified plan gate. A plan written to PLAN.md must carry a certificate (premises, files
to change, tests) and no step may contradict an active decision. Checked before Agent mode acts."""
import re
import time

from . import jev, policy, questions as Q

SECTIONS = {"premises": r"premises|assumptions", "files": r"files?\b", "tests": r"tests?\b"}


def steps_of(text):
    return [re.sub(r"^\s*([-*]|\d+[.)])\s*", "", l).strip()
            for l in text.splitlines() if re.match(r"\s*([-*]|\d+[.)])\s+\S", l)][:20]


def check(store, text):
    t0 = time.time()
    headings = " ".join(re.findall(r"^#+\s*(.+)$", text, re.M)).lower()
    missing = [k for k, pat in SECTIONS.items() if not re.search(pat, headings)]
    steps = steps_of(text)
    decisions = store.active_decisions(kind="limit")
    viol, tok = {}, 0
    if steps and decisions:
        qs = {f"s{i}_{d['id']}": Q.plan_step_violates(i, d["id"]) for i in range(len(steps)) for d in decisions}
        answers, usage = jev.ask({"steps": steps, "decisions": {d["id"]: d["text"] for d in decisions}}, qs)
        tok = jev.tokens(usage)
        viol = {k: a["noul"] for k, a in answers.items()}
    risks = {"violates": max(viol.values(), default=0.0), "uncertified": 1.0 if missing else 0.0}
    worlds, reveal = policy.independent(risks)
    d = policy.decide(worlds, reveal, policy.PLAN_HARM, risks=risks)
    store.log({"stage": "plan", **d.as_dict(), "missing_sections": missing, "tokens": tok,
               "ms": int((time.time() - t0) * 1000)})
    if d.action == "allow":
        return 0, "", ""
    msg = ["Hall Monitor plan gate: revise PLAN.md before implementing."]
    if missing:
        msg.append("- missing certificate sections: " + ", ".join(missing) +
                   " (state premises, the exact files you will change, and the tests that prove it)")
    texts = {d["id"]: d["text"] for d in decisions}
    for n, (k, p) in enumerate(sorted(viol.items(), key=lambda kv: -kv[1])):
        if p >= 0.5 or n == 0 and p >= 0.25:
            i, did = k[1:].split("_", 1)
            msg.append(f"- step \"{steps[int(i)]}\" contradicts {did} \"{texts[did]}\" (p={p:.2f})")
    return 2, "", "\n".join(msg)
