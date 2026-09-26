---
name: certified-plan
description: Write an implementation plan as a certificate that Hall Monitor can check before any code changes. Use in Plan mode in a repository supervised by Hall Monitor.
---

# Certified plan

A certified plan states its premises, the exact files it will change and the tests that will prove it,
so that it can be checked against the project's decisions before Agent mode starts.

<Steps>
<Step>Call `list_decisions` and read them.</Step>
<Step>Write PLAN.md with exactly these sections:
- `## Premises`: facts about the codebase the plan relies on, each with the file that shows it.
- `## Files to change`: numbered steps, each naming the file(s) it changes and what changes.
- `## Tests`: the tests that will fail if the change is wrong.</Step>
<Step>No step may break an active decision. If the best plan needs to, say so and ask the user first.</Step>
<Step>Writing PLAN.md triggers Hall Monitor's plan gate. If it is blocked, revise the named steps or add
the missing sections and write it again.</Step>
</Steps>
