---
name: extract-decisions
description: Turn the rules in a policy document, ADR, spec or AGENTS.md (.pdf, .docx, .xlsx or .md) into decisions Hall Monitor enforces. Use when a task references such a document or the user runs /decisions.
---

# Extract decisions from a document

<Steps>
<Step>Read the whole document. PDF files can be read directly; for .docx and .xlsx use office_read (read_file hands Office files to it automatically).</Step>
<Step>Find every sentence that constrains how this codebase may change: things that are forbidden,
required approvals, technology choices, required tests, required docs. Skip background and rationale.</Step>
<Step>For each one, call `record_decision` with:
- `text`: the rule restated as one short imperative sentence (e.g. "Do not modify app/auth.py without a security review.")
- `source`: the document path, plus section or page if known (e.g. "docs/security-policy.pdf §2")
- `quote`: the exact sentence from the document</Step>
<Step>If a decision comes back REJECTED because it contradicts a higher-authority decision, report the
conflict to the user instead of recording it differently.</Step>
<Step>Finish with `list_decisions` and summarize for the user which rules are now enforced, and which are
checked per action versus on the finished work.</Step>
</Steps>
