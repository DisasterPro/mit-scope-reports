# Pull Reports

Manual fallback to pull scope reports from the private `EncircleInc/joe-sandbox` repo.

Under normal operation, `/ea` automatically pulls `2_scope-eval-all-runs.md` before each enhancement run (Step 0). This skill is for manually refreshing the usage, cost, and error reports, or for pulling all reports at once.

## Step 1: Run pull-reports.sh

Run the pull script via Bash:

```bash
cd /workspaces/ai-services/services/mitigation-scope && joe/scripts/pull-reports.sh
```

This script:
1. Uses gh CLI or git credential fallback to fetch files from the private joe-sandbox repo
2. Merges `joe/evals/traces/2_scope-eval-all-runs.md` preserving locally enhanced traces (Bug Assessments survive)
3. Appends new entries to `joe/docs/reports/scope-usage.md`, `scope-costs.md`, `scope-errors.md`
4. Recomputes All-Time Summary headers for all three report files

## Step 2: Summary

After the script completes, display what was updated:

```
## Pull Reports Summary

| Report | Status | Notes |
|--------|--------|-------|
| 2_scope-eval-all-runs.md | {Merged/Skipped} | {N} remote traces, {N} local enhanced preserved |
| scope-usage.md | {Updated/Skipped} | {total scopes} scopes, {days} days |
| scope-costs.md | {Updated/Skipped} | {total traces} traces, avg ${cost} |
| scope-errors.md | {Updated/Skipped} | {error rate}% error rate |
```
