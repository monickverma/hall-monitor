---
description: Submit your completion claims to Hall Monitor for verification
---
Call the hall-monitor list_evidence tool. Then list one specific claim per thing you changed in this task, each citing the IDs of the receipts that prove it (for claims about tests, cite a test run made after your last edit), and call the hall-monitor submit_claims tool with them, for example `[{"claim": "...", "evidence": ["E7", "E9"]}]`. For every claim that comes back not verified, fix the work or correct the claim, re-run the tests and submit again with fresh receipts. If an AUDIT is requested, spawn an explore subagent with the brief and resubmit with its findings.
