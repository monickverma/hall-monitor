---
name: claim-audit
description: Independently audit whether a claim about a code change is true, by reading the code and tests. Use in the Receipts Auditor mode or as an explore subagent when Hall Monitor requests an AUDIT.
---

# Audit a claim

You are checking someone else's claim. Do not trust it, and do not edit anything.

<Steps>
<Step>Restate the claim as a checkable statement: which behavior, in which file, verified by which test.</Step>
<Step>Read the changed files and find the code that implements the behavior. Cite file:line.</Step>
<Step>Read the tests. For each test that supposedly checks the behavior, say which assertion would fail
if the behavior were broken. A test with no such assertion does not check it.</Step>
<Step>If Hall Monitor listed surviving sabotage mutants, explain for each one why no test caught it.</Step>
<Step>End with one line: `VERDICT: holds` or `VERDICT: does not hold` or `VERDICT: cannot tell`, followed
by the single most important piece of evidence.</Step>
</Steps>
