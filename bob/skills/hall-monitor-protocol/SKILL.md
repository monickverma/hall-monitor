---
name: hall-monitor-protocol
description: How to work in a repository supervised by Hall Monitor. Use at the start of any implementation task when the hall-monitor MCP server is connected or the Supervised mode is active.
---

# Working under Hall Monitor

Hall Monitor enforces the project's recorded decisions on every action and verifies every claim you
make about your work. Its hooks block actions; its MCP tools answer you directly.

<Steps>
<Step>Call `list_decisions` to see the rules in force. "limit" rules are checked on every action;
"obligation" rules are checked on the finished work.</Step>
<Step>If the user or the task points to a policy document, ADR or spec, use the `extract-decisions`
skill so its rules are recorded before you start.</Step>
<Step>Before each edit or command, call `declare_intent` with one or two sentences saying what you will
do and why, plus the exact files and commands. State the plain reason. Hall Monitor recognizes
rationalizations such as "just this once", "we'll fix it later", "the spirit of the rule allows it" or
"it's faster", and rejects them.</Step>
<Step>If the intent comes back REJECTED, do not try the action anyway (it will be blocked). Choose an
approach that respects the decisions, or ask the user whether the decision should change.</Step>
<Step>Only do what you declared. An edit that does something other than its declared intent is blocked.</Step>
<Step>If any tool call is reported as blocked, call `explain_block`. Bob's hooks can stop a tool but
cannot tell you why; `explain_block` returns Hall Monitor's reason and what to do instead.</Step>
<Step>Parallel work: Hall Monitor checks every subagent's brief against the goal, the decisions and the
other agents' work before it starts, and checks its summary when it returns. A drifted result is reported
in your next declare_intent result. Give each subagent a precise task, and in a `general` subagent's task
add: "Before editing, call declare_intent with agent=<your name> and agent_task=<this task>. If you
submit claims, call submit_claims with agent=<your name>." The project's rules are checked on your own
(the main agent's) submission, when the whole task is done.</Step>
<Step>Hall Monitor records every edit and command you make as a numbered receipt (E1, E2, ...). A passing
test run also becomes a checkpoint you can go back to. If a command fails, your next `declare_intent` must
say how you'll deal with the failure.</Step>
<Step>When the task is done, call `list_evidence`, then call `submit_claims` with one specific claim per
thing you did, each citing the receipts that prove it, e.g. `{"claim": "Added a test that fails if the 6th
login attempt within a minute is allowed", "evidence": ["E7", "E9"]}`. For claims about tests, cite a test
run made after your last edit. Each claim is checked against its receipts, the diff, a fresh test run and
sabotage probes (the changed code is deliberately broken to see whether your tests notice).</Step>
<Step>Fix every claim that is not verified (or correct the claim), re-run the tests, and submit again with
fresh receipts. After two send-backs Hall Monitor stops the repair loop and hands the decision to the user.
If Hall Monitor asks for an AUDIT, spawn an `explore` subagent with the brief it gives you and pass the
subagent's findings back in `audit_notes`.</Step>
<Step>Finish with `/hall-pass`: call `hall_pass`, then publish the report as a shareable one-page summary
with `create_html_artifact`, and give the user its link and the file path.</Step>
</Steps>
