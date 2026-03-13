# Fix Validate

After implementing a pipeline fix for a tracked issue, re-run all affected traces and verify the fix resolved the problem. Version-aware -- uses `/et` for each trace, which only surfaces net-new issues.

## Usage

`/fv <issue_number>`

Arguments: `$ARGUMENTS` (issue number from changes-to-be-made.md)

## Process

### Step 1: Parse Issue Number

Extract issue number from `$ARGUMENTS` (e.g., `7` from `/fv 7`).

### Step 2: Look Up Issue

Read `joe/evals/traces/5_changes-to-be-made.md`. Find the issue by number. Extract:
- Issue description
- Priority
- Affected trace IDs (from the Traces column)
- Failing eval names (from the Issue Details section)
- Files affected

If the issue number is not found, notify user and stop.

### Step 3: Run Evals on Affected Traces

For each affected trace ID:
1. Run `/et {trace_id} --label "Fix validation for Issue {N}"`
2. Collect the eval results, specifically the results for the evals that were failing for this issue

### Step 4: Compare Results

For each trace, check whether the specific evals that flagged this issue now pass:
- **RESOLVED**: All flagged evals now PASS for this trace
- **PARTIAL**: Some flagged evals now PASS, others still FAIL
- **UNRESOLVED**: All flagged evals still FAIL

### Step 5: Report

Print a validation summary:

```
## Fix Validation: Issue {N}

**Issue:** {one-sentence description}
**Priority:** {priority}
**Evals:** {eval_names}

### Results

| Trace | Previous | Current | Status |
|---|---|---|---|
| {trace_id} | {X} FAIL | {Y} FAIL | RESOLVED/PARTIAL/UNRESOLVED |

### Verdict: {RESOLVED / PARTIAL / UNRESOLVED}

{If RESOLVED: "All affected traces now pass the relevant evals. Issue {N} can be marked as fixed."}
{If PARTIAL: "X of Y traces improved. Remaining failures: {detail}"}
{If UNRESOLVED: "No improvement detected. The fix may not address the root cause, or the traces may need to be re-run through the updated pipeline."}
```

### Step 6: Update Changes To Be Made (if resolved)

If ALL traces are RESOLVED:
- Add a note to the issue in changes-to-be-made.md: "**Status:** Fixed in {current_version} -- validated {date}"
- Update version_changelog.md to record that this issue was fixed in the current version

## Notes

- This skill is most useful AFTER deploying a fix and getting new traces through the updated pipeline
- For pre-deployment validation, it confirms whether the eval criteria would pass given the current pipeline behavior
- Each `/et` call is fully version-aware and populates INDEX.md normally
- If a trace was run on an old pipeline version, the version-aware filtering in `/et` will mark old-version issues as resolved automatically
