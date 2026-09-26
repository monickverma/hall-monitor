---
description: Export the decision ledger and the latest receipts to an Excel workbook
argument-hint: <path to .xlsx, e.g. docs/hall-monitor-ledger.xlsx>
---
Call the hall-monitor list_decisions tool, and read .hallmonitor/receipts.json if it exists. Use office_edit to write $1 with two sheets: "Decisions" (ID, rule, kind, source) and "Receipts" (claim, verdict, action, judged by). Then validate the file with office_read in validate mode and tell me the result.
