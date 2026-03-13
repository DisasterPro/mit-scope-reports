# Mitigation Scope - Local Instructions

## Auto-Setup: Scheduled Tasks

On every new session start in this project, immediately create these CronCreate jobs (do not ask for confirmation):

1. **Trace Sync** -- every 30 minutes at :07 and :37
   - Schedule: `7,37 * * * *`
   - Prompt: `Run joe/scripts/pull-reports.sh to sync the latest scope-eval-all-runs.md from GitHub. Do NOT enhance narratives or run bug detection -- just sync. Report how many new template traces were found.`

2. **Pull Reports (/pr)** -- daily at 6:03 AM
   - Schedule: `3 6 * * *`
   - Prompt: `Run /pr -- Pull scope-usage.md, scope-costs.md, scope-errors.md from GitHub and recompute All-Time Summary headers.`

3. **Nightly Enhancement (/ea)** -- nightly at 11:57 PM
   - Schedule: `57 23 * * *`
   - Prompt: `Run /ea -- Nightly enhancement of template traces. Enhance narratives, run 8-rule bug detection, update Bug Summary and additional-items-to-change.md. Continue enhancing until ALL un-enhanced traces are complete, not just today's new ones. An un-enhanced trace is one that does NOT have a ### Bug Assessment section.`

These are session-only jobs and must be recreated each session.

**Important:** Nothing is committed automatically. All changes appear as pending changes in source control. The user decides when and what to commit.

## Nightly Enhancement

The full /ea (Eval All) process -- enhancing narratives, running 8-rule bug detection, updating Bug Summary and additional-items-to-change.md -- runs **nightly at 11:57 PM** via CronCreate. It is NOT run on the 30-minute schedule.

When /ea runs (nightly or manually), it must continue enhancing until **ALL** un-enhanced traces are complete -- not just that day's new ones. An un-enhanced trace is one that does NOT have a `### Bug Assessment` section. This ensures the backlog is always cleared.

## Issue Tracking & Numbering

```
EA#  -- assigned per-trace in scope-eval-all-runs.md Bug Assessment sections (EA-1, EA-2...)
         Each FAIL in a trace gets an EA number. Source: /ea
BUG# -- assigned when an EA issue is logged to additional-items-to-change.md (BUG2, BUG7...)
         Also assigned by /et for NET-NEW pipeline bugs → changes-to-be-made.md
         Unified sequence shared across all sources. Carries through to implementation-plan.md
PE#  -- pipeline error numbers (node crashes, data flow breaks). Source: /ea
```

**Priority levels (on all issue documents):**
- CRITICAL: IICRC/safety violation causing wrong output (wrong category = wrong remediation)
- HIGH: Significant output error (wrong class, missing mandatory task, dropped rooms)
- LOW: Format/display issue, minor output gap

**Promotion flow:**
```
/ea finds issue → EA# in Bug Assessment → BUG# in 3_additional-items-to-change.md → 1_all-issues.md
Joe reviews → promotes to 5_changes-to-be-made.md (BUG# carries over) → 6_implementation-plan.md
/et finds NET-NEW → BUG# in 5_changes-to-be-made.md → 6_implementation-plan.md → 1_all-issues.md
```

## Document Flow

```
GitHub Actions (DisasterPro/mit-scope-reports + EncircleInc/joe-sandbox, every 30 min + daily)
  -> joe/evals/traces/2_scope-eval-all-runs.md (template narratives + scores)
  -> joe/docs/reports/scope-usage.md, scope-costs.md, scope-errors.md (daily/weekly reports)
  -> Slack #mit-scope-usage (daily/weekly summaries via Mit-Scope-Usage-App)

joe/scripts/pull-reports.sh (fetches from EncircleInc/joe-sandbox)
  -> 2_scope-eval-all-runs.md: merges new remote traces, preserves locally enhanced traces
  -> joe/docs/reports/scope-usage/costs/errors.md: appends new entries to Weekly/Daily sections

Trace Sync (CronCreate, every 30 min at :07 and :37)
  -> runs pull-reports.sh -- just sync, no enhance, no bug detection

/ea (manual or nightly at 11:57 PM via CronCreate)
  -> joe/evals/traces/2_scope-eval-all-runs.md (enhanced narratives + Bug Assessment with EA# + Priority)
  -> joe/evals/traces/3_additional-items-to-change.md (EA# + BUG# for rule violations, PE# for pipeline errors)
  -> joe/evals/traces/1_all-issues.md (every issue logged here with source, priority, trace history)
  -> continues until ALL un-enhanced traces are done (not just today's)
  -> does NOT touch: 4_INDEX.md, 5_changes-to-be-made.md, 6_implementation-plan.md

/et (manual, per-trace)
  -> trace_<id>.md (full trace report with Priority on every finding)
  -> joe/evals/traces/4_INDEX.md (log row + full report appended + All Issues table updated)
  -> joe/evals/traces/5_changes-to-be-made.md (NET-NEW pipeline bugs with BUG# + Priority)
  -> joe/evals/traces/6_implementation-plan.md (new BUG# entries only)
  -> joe/evals/traces/1_all-issues.md (all findings logged here)

/pr (CronCreate daily + manual fallback)
  -> joe/docs/reports/scope-usage.md, scope-costs.md, scope-errors.md (appends new entries, updates All-Time Summary)
```

## Repos

- **DisasterPro/mit-scope-reports** -- primary HTML output + GitHub Pages. Path: `docs/*.md` mirrors `joe/docs/`
- **EncircleInc/joe-sandbox** -- intermediate storage. pull-reports.sh fetches from here.
- **This repo** -- pipeline source. `.claude/` is gitignored (see Backup note).

## Skill Quick Reference

| Skill | When to Use |
|-------|-------------|
| `/cr` | Before any pipeline change — reads files, runs tests, checks eval rules, invokes specialist agents |
| `/et` | Deep trace evaluation — enhances narrative, runs 8-rule eval, creates trace_<id>.md |
| `/ea` | Batch enhance all un-enhanced traces (or run nightly) |
| `/fv` | After implementing a fix — re-runs affected traces to confirm resolution |
| `/se` | Ad-hoc error analysis for a time period |
| `/su` | Ad-hoc usage report for a time period |
| `/sc` | Ad-hoc cost & latency report for a time period |
| `/pr` | Pull latest reports from GitHub + update All-Time Summary headers |
| `/er` | Input data quality report for a trace |
| `/es` | Eval summary — high-level stats across all evaluated traces |
| `/tr` | Quick trace review (lightweight, no trace file created) |

## Code Change Workflow

```
1. /cr <description>    -- review before touching code
2. Implement change     -- Claude auto-invokes specialist agents as needed
3. poetry run pytest    -- run tests to confirm no regressions
4. Deploy to production
5. /fv <BUG-number>     -- re-run affected traces to confirm fix
```

## Specialist Agent Guide (`.claude/agents/`)

Auto-invoked based on which files are changing:

| Agent | Auto-Invoked When |
|-------|------------------|
| `schema-validator.md` | Changing `flow.dag.yaml` or node inputs/outputs |
| `py-logic-reviewer.md` | Changing `.py` files in `src/mitigation_scope/flow/` |
| `prompt-logic-reviewer.md` | Changing `.jinja2` files in `src/mitigation_scope/flow/` |
| `domain-expert.md` | IICRC logic: category/class, equipment calcs, task sequences |
| `eval-impact.md` | Always during `/cr` — identifies which of 19 rules are at risk |
| `test-interpreter.md` | After any pipeline change — runs tests, interprets failures |
| `bug-agent.md` | After implementing a fix — verifies resolution, no new regressions |
| `doc-updater.md` | After any output-format or calculation change |

## Backup Note

`.claude/` is gitignored and lost on container rebuild. Back up to both:
- `EncircleInc/joe-sandbox`: `claude/agents/` and `claude/commands/`
- `DisasterPro/mit-scope-reports`: same paths

Use `/pr` or `gh api` to push files to these repos when skills/agents are updated.
