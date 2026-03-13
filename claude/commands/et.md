# Eval Trace

Run all 19 evaluations against a Langfuse trace. Produce a full shareable evaluation report. Log ALL issues to INDEX.md (ranked by frequency). Publish only NET-NEW pipeline bugs to changes-to-be-made.md (BUG-numbers) and implementation-plan.md.

## Arguments

`$ARGUMENTS` is the trace_id. It may be a full Langfuse URL or just the ID string. Extract the trace ID (hex string).

## Step 1: Fetch Trace and Context

1. Fetch the trace from Langfuse using the REST API:
   ```
   curl -sf -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
     "$LANGFUSE_HOST/api/public/traces/$TRACE_ID"
   ```
   If env vars aren't set, use:
   - Public key: pk-lf-22691c65-afad-4a1c-a248-ea814efa2153
   - Secret key: sk-lf-61e4e7d9-c48e-4325-90a7-6666e189a83d
   - Host: https://us.cloud.langfuse.com

2. Read `joe/evals/version_changelog.md` to get the current pipeline version.
3. From the trace metadata, extract the trace's pipeline version:
   - Check `trace.metadata.version` field first
   - If empty, check `trace.version` or `trace.release`
   - If neither found, record as "unknown"

## Step 2: Extract Node Outputs

Fetch observations for the trace:
```
curl -sf -u "AUTH" "$LANGFUSE_HOST/api/public/observations?traceId=$TRACE_ID&limit=50"
```

Then fetch detailed output for each key pipeline node by observation ID:
- **Description**, **Merge**, **RoomsWithId**, **Tasks**, **Equipment**, **Drying**, **Standards**, **PropertyImagesAggregator**, **Assembly**

Build a compact **input_summary**:
- Property address, loss type, loss date
- Room count, photo count, floor plan count
- Whether guidelines/user_instructions exist
- Moisture monitoring data presence

Also detect for the What Was Provided table (same categories as /ea):
- **Structures**: Count total, classify structural vs organizational
- **Rooms**: Total, affected, unaffected, organizational from RoomsWithId.metrics
- **Technician Notes**: Count `<NOTE>` tags in input description
- **Video Transcripts**: Count `<ROOM_VIDEO>` tags
- **Thermal Images**: Scan property_images for thermal/FLIR/IR keywords
- **360 Photos**: Scan property_images for 360/pano keywords
- **General Notes**: Check for `## General Notes` section
- **Floor Plans**: Count measurement_images, check room name matching
- **Moisture Data**: Check for moisture readings in input
- **Guidelines**: Check for guidelines section

Save extracted data to temp files for agent consumption:
- `/tmp/et_trace_input.json` -- input_summary + input description
- `/tmp/et_agent1_data.json` -- input description, Description output, final scope
- `/tmp/et_agent2_data.json` -- input, Description, Merge, RoomsWithId, MeasurementImages, PropertyImagesAggregator, final scope
- `/tmp/et_agent3_data.json` -- Description, Merge, Tasks, Equipment, Drying, Standards, final scope

**Large trace truncation** (20+ rooms in Merge output):
- Cap Merge rooms at 20, materials at 30
- Cap Tasks rooms at 15

## Step 3: Launch 3 Evaluation Agents in Parallel

Launch 3 agents simultaneously using the Agent tool (`subagent_type="general-purpose"`). Each agent runs its assigned evaluations.

### Agent 1 Prompt: Classification + Hazards (6 evals)

```
You are an IICRC standards evaluator. Evaluate this mitigation scope trace against 6 rules.

DATA FILE: /tmp/et_agent1_data.json
Read this file to get: input description, Description node output, and final scope.

EVALS TO RUN (read each rule file, then evaluate):
1. joe/evals/rules/water_category.md
2. joe/evals/rules/water_class.md
3. joe/evals/rules/mold_fire.md
4. joe/evals/rules/iicrc_references.md
5. joe/evals/rules/job_type.md
6. joe/evals/rules/asbestos_lead.md

For EACH eval:
1. Read the rule file from joe/evals/rules/
2. Read the relevant data from the data file
3. Apply the rules to the data
4. Produce a result

Return your results in this EXACT format (one block per eval, separated by blank lines):

EVAL: water_category
RESULT: PASS or FAIL
REASON: one sentence explanation
FAILURE_MODE: (only if FAIL) standard_violation or hallucination
DETAILS: SOURCE_IDENTIFIED=<source>, EXPECTED=<n>, ACTUAL=<n>
```

### Agent 2 Prompt: Room & Data (7 evals)

```
You are a data integrity evaluator. Evaluate this mitigation scope trace against 7 rules.

DATA FILE: /tmp/et_agent2_data.json

EVALS TO RUN:
1. joe/evals/rules/room_integrity.md
2. joe/evals/rules/math_calculations.md
3. joe/evals/rules/measurement_integrity.md
4. joe/evals/rules/material_consistency.md
5. joe/evals/rules/material_room_integrity.md
6. joe/evals/rules/hallucination.md
7. joe/evals/rules/narrative_consistency.md

Return results in EXACT format: EVAL/RESULT/REASON/FAILURE_MODE/DETAILS
```

### Agent 3 Prompt: Tasks & Equipment (6 evals)

```
You are a task sequencing and equipment evaluator. Evaluate this mitigation scope trace against 6 rules.

DATA FILE: /tmp/et_agent3_data.json

EVALS TO RUN:
1. joe/evals/rules/task_sequence.md
2. joe/evals/rules/task_tense.md
3. joe/evals/rules/equipment.md
4. joe/evals/rules/drying_format.md
5. joe/evals/rules/emergency_services.md
6. joe/evals/rules/standards_display.md

Return results in EXACT format: EVAL/RESULT/REASON/FAILURE_MODE/DETAILS
```

## Step 4: Collect and Classify Results

After all 3 agents return:

1. Parse each agent's output to extract EVAL/RESULT/REASON/FAILURE_MODE/DETAILS blocks.
2. Compute overall score: `<pass_count>/19`.
3. For each FAIL, classify as **NET-NEW** or **RESOLVED** using deterministic lookup:

   a. Read `joe/evals/traces/3_additional-items-to-change.md`. Match FAIL to known bug by eval name + failure description.
   b. Read `joe/evals/version_changelog.md`. Look up the bug identifier in **Bug IDs Fixed**:
      - Fix version > trace version → **RESOLVED (Vxx)**
      - Fix version ≤ trace version → **NET-NEW**
   c. No match → **NET-NEW** (newly discovered)

4. For each FAIL, classify as **Pipeline bug** or **Input quality**:
   - **Pipeline bug**: Pipeline could have done better with the given input
   - **Input quality**: Input was insufficient

5. For pipeline bugs, assign **Priority**:
   - **CRITICAL**: IICRC/safety violations causing wrong output
   - **HIGH**: Significant output errors
   - **LOW**: Format/display issues

## Step 5: Write Trace Evaluation Report

Write to `joe/evals/traces/trace_<first_8_chars_of_trace_id>.md`.

This is a **shareable, user-facing document** — same bulleted, scannable style as /ea enhanced narratives. It should give anyone reading it a complete picture of this scope run: what was provided, what the system did, what issues exist, and what to do about them.

```markdown
# Trace Evaluation: <trace_id>

**Date:** <YYYY-MM-DD HH:MM UTC> | **Version:** <version> | **User:** <user_email>
**Score:** <pass_count>/19 | **Time:** <processing_time>
**Rooms:** <total> total (<affected> affected, <unaffected> unaffected) | **Photos:** <n> | **Notes:** <n> | **Floor Plans:** <n>

## What Was Provided

| Category | Status | Details |
|----------|--------|---------|
| Structures | ... | ... |
| Rooms | ... | ... |
| Room Setup | ... | ... |
| Field Photos | ... | ... |
| Thermal Images | ... | ... |
| 360 Photos | ... | ... |
| Video Transcripts | ... | ... |
| General Notes | ... | ... |
| Technician Notes | ... | ... |
| Floor Plans | ... | ... |
| Room Name Matching | ... | ... |
| Moisture Data | ... | ... |
| Guidelines | ... | ... |

## Input Assessment
- [bulleted, specific to THIS trace]
- [what was submitted, quality, gaps]

## Issue Assessment
- [bulleted, each data quality issue found]
- [distinguish input-caused vs system-caused]

## Recommendations
1. **[title].** [why it matters, what to do]
(3-5 items; floor plan room name mismatch is #1 if detected)

## Pipeline Assessment
- [bulleted, processing details, system behavior]

## Evaluation Results

**Score:** <pass_count>/19 | **NET-NEW bugs:** <n> | **RESOLVED:** <n>

| # | Eval | Result | Priority | Type | Reason |
|---|------|--------|----------|------|--------|
| 1 | water_category | PASS/FAIL | --/CRITICAL/HIGH/LOW | --/NET-NEW/RESOLVED | reason |
| 2 | water_class | ... | ... | ... | ... |
...19 rows...

## Failure Details

(For each FAIL:)

### <eval_name> — <NET-NEW/RESOLVED> — <CRITICAL/HIGH/LOW>

- **What happened:** [one sentence describing the violation]
- **Expected:** [what should have happened per the rule]
- **Actual:** [what the system actually did]
- **Node:** <pipeline node where the violation occurs>
- **Impact:** [why this matters for the scope output]
- **Bug #:** <BUG-number if assigned, or "New" if newly discovered>

## Bug Assessment

(Same format as /ea Bug Assessment table for cross-reference)

| EA # | Rule | Priority | Result | Node | Details |
|------|------|----------|--------|------|---------|
...8 rows for the /ea rule subset (water_category, water_class, room_integrity, hallucination, task_sequence, equipment, task_tense, material_room_integrity)...

**Rules Checked:** 19/19 | **Bugs Found:** <n>
```

**Narrative rules (same as /ea):**
- Bulleted, scannable, simple language
- No internal node names in narrative text (say "the system" not "Assembly")
- No fabrication — only state what the data shows
- No cost, pricing, or PLX references
- Floor plan room name mismatch is #1 recommendation when detected
- Specific to THIS trace, not generic

## Step 6: Update INDEX.md

Read `joe/evals/traces/4_INDEX.md`. Update ALL sections:

### 6A: Add to Trace Log
Append row: `| <date> | <trace_8> | <version> | <score>/19 | <failed_evals_list> |`
If trace already exists, update existing row.

### 6B: Update All Issues (Ranked by Frequency)
For each failed eval: increment occurrences or add new row. Re-sort by Occurrences descending, renumber Rank.

### 6C: Recompute Summary Stats
Recompute Total, Avg Score, Score Distribution from all Trace Log rows.

### 6D: Append Full Report
Add/replace `### Trace: <trace_8> — <date>` subsection under `## Trace Reports` at bottom of INDEX.md. Paste full contents of the trace report from Step 5.

## Step 7: Update changes-to-be-made.md (NET-NEW Pipeline Bugs Only)

For each FAIL that is BOTH **NET-NEW** AND a **pipeline bug**:

1. Read `joe/evals/traces/5_changes-to-be-made.md` and `joe/evals/traces/3_additional-items-to-change.md`
2. If existing bug: add trace_id to Traces column
3. If new bug: assign next BUG-number, add to Quick Reference + detail section

## Step 7B: Update implementation-plan.md
For new BUG-numbers: add to Master Priority Table + detail section in `joe/evals/traces/6_implementation-plan.md`.

## Step 7C: Update all-issues.md
For each FAIL: update or add entry in `joe/evals/traces/1_all-issues.md`.

## Step 7D: Update scope-eval-all-runs.md
If this trace exists in `joe/evals/traces/2_scope-eval-all-runs.md`:
1. Add the `### Bug Assessment` table (8-rule subset) to the trace section
2. Update the Bugs column in the index table
3. If the trace still has template narratives, enhance them using the Langfuse data already fetched (same as /ea Step 2)

This ensures /et results flow back into the /ea file for consistency.

## Step 8: Display Summary

```
Trace <trace_8> evaluated: <pass_count>/19

NET-NEW: <list with priority or "None">
RESOLVED: <list or "None">
PASS: <count> evals passed

Report: joe/evals/traces/trace_<id>.md
INDEX updated: <n> issues tracked, <n> traces total
```
