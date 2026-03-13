# Eval Summary

Display the aggregate evaluation stats from INDEX.md. The stats are maintained inline by /et -- this command simply reads and presents them in chat.

## Arguments

`$ARGUMENTS` is ignored. This command takes no arguments.

## Step 1: Read INDEX.md

Read `joe/evals/traces/4_INDEX.md`.

If the Trace Log table has no data rows, reply: "No traces have been evaluated yet. Run `/et <trace_id>` to evaluate a trace."

## Step 2: Read Supporting Documents

Also read:
- `joe/evals/traces/3_additional-items-to-change.md` -- for open pipeline bug count and details
- `joe/evals/version_changelog.md` -- for current version context

## Step 3: Display in Chat

Present the INDEX.md data in a clean chat-friendly format. Pull directly from the document -- do NOT recompute stats (they are already maintained by /et).

Reply with:

```
## Eval Summary

(Copy the Summary section from INDEX.md: total, avg score, last updated, score distribution table)

### All Issues (Top 10)

(Copy the top 10 rows from the All Issues table, already ranked by frequency)

### Open Pipeline Bugs

(From additional-items-to-change.md Quick Reference table -- list open issues with priority and trace count. If none: "No open pipeline bugs.")

### Recent Traces (Last 5)

(Last 5 rows from the Trace Log, most recent first)

### Version Breakdown

(Group Trace Log rows by Version column, show count and avg score per version)
```

The Version Breakdown is the only thing computed fresh -- group the Trace Log rows by their Version column and calculate count + average score for each version. Everything else is read directly from the documents.
