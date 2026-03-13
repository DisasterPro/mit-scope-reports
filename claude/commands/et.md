# Eval Trace

Run all 19 evaluations against a Langfuse trace. Log ALL issues to INDEX.md (ranked by frequency). Publish only NET-NEW pipeline bugs to changes-to-be-made.md (BUG-numbers) and implementation-plan.md.

## Arguments

`$ARGUMENTS` is the trace_id. It may be a full Langfuse URL or just the ID string. Extract the trace ID (hex string).

## Step 1: Fetch Trace and Context

1. Call `mcp__langfuse__fetch_trace` with trace_id, `include_observations=true`, `output_mode="full_json_file"`. Note the saved file path.
2. Read `joe/evals/version_changelog.md` to get the current pipeline version.
3. From the trace metadata, extract the trace's pipeline version:
   - Check `trace.version` field first
   - If empty, check `trace.release` (git commit hash) and match to changelog
   - If neither found, record as "unknown"

## Step 2: Extract Node Outputs

From the saved trace JSON, use Bash with python3 to extract each pipeline node's output by matching observation `name`:
- **Description**: observation name="Description"
- **Merge**: observation name="Merge"
- **RoomsWithId**: observation name="RoomsWithId"
- **Tasks**: observation name="Tasks"
- **Equipment**: observation name="Equipment"
- **Drying**: observation name="Drying"
- **Standards**: observation name="Standards"
- **MeasurementImages**: observation name="MeasurementImages"
- **PropertyImagesAggregator**: observation name="PropertyImagesAggregator"
- **Assembly**: observation name="Assembly"
- **Final scope**: `trace.output.scope`
- **Input**: `trace.input` (description, property_images count, measurement_images count, guidelines)

Build a compact **input_summary** string:
- Property address, loss type, loss date
- Room count (from input description), photo count, floor plan count
- Whether guidelines/user_instructions exist
- Any moisture monitoring data present

Also detect for enhanced input audit (add to input_summary — these populate the What Was Provided table):
- **Structures**: Count total structures (rooms + org items) submitted. Identify which match org patterns (Initial Visit, Cause of Loss, Data, Checklist, Documentation, Admin, Photo, Video). Record count of real rooms vs organizational.
- **Technician Notes**: Count `<NOTE>` tags in trace.input.description (written notes only). Count how many are attached to a room structure vs orphan (not attached to any room). Format: `X notes; Y with rooms, Z without rooms`.
- **Video Transcripts**: Count `<ROOM_VIDEO>` tags in trace.input.description. Format: `X room video transcripts`.
- **Thermal Images**: Scan `trace.input.property_images` filenames/metadata for "thermal", "FLIR", "IR", "infrared", "heat". Count found.
- **360 Photos**: Scan `trace.input.property_images` for "360", "pano", "panoramic", "equirectangular", "sphere". Count found.

**Large trace truncation** (20+ rooms in Merge output):
- Cap Merge rooms at 20, materials at 30
- Cap Tasks rooms at 15

Save extracted node outputs to temp files for agent consumption:
- `/tmp/et_trace_input.json` -- input_summary + input description
- `/tmp/et_agent1_data.json` -- input description, Description output, final scope
- `/tmp/et_agent2_data.json` -- input, Description, Merge, RoomsWithId, MeasurementImages, PropertyImagesAggregator, final scope
- `/tmp/et_agent3_data.json` -- Description, Merge, Tasks, Equipment, Drying, Standards, final scope

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

(repeat for each eval)
```

### Agent 2 Prompt: Room & Data (7 evals)

```
You are a data integrity evaluator. Evaluate this mitigation scope trace against 7 rules.

DATA FILE: /tmp/et_agent2_data.json
Read this file to get: input, Description, Merge, RoomsWithId, MeasurementImages, PropertyImagesAggregator, final scope.

EVALS TO RUN (read each rule file, then evaluate):
1. joe/evals/rules/room_integrity.md
2. joe/evals/rules/math_calculations.md
3. joe/evals/rules/measurement_integrity.md
4. joe/evals/rules/material_consistency.md
5. joe/evals/rules/material_room_integrity.md
6. joe/evals/rules/hallucination.md
7. joe/evals/rules/narrative_consistency.md

For EACH eval:
1. Read the rule file
2. Read relevant data from the data file
3. Apply rules to data
4. Produce result

Return results in this EXACT format:

EVAL: room_integrity
RESULT: PASS or FAIL
REASON: one sentence
FAILURE_MODE: (only if FAIL) data_flow_break or hallucination
DETAILS: <relevant output fields from the rule's Output Fields section>

(repeat for each eval)
```

### Agent 3 Prompt: Tasks & Equipment (6 evals)

```
You are a task sequencing and equipment evaluator. Evaluate this mitigation scope trace against 6 rules.

DATA FILE: /tmp/et_agent3_data.json
Read this file to get: Description, Merge, Tasks, Equipment, Drying, Standards, final scope.

EVALS TO RUN (read each rule file, then evaluate):
1. joe/evals/rules/task_sequence.md
2. joe/evals/rules/task_tense.md
3. joe/evals/rules/equipment.md
4. joe/evals/rules/drying_format.md
5. joe/evals/rules/emergency_services.md
6. joe/evals/rules/standards_display.md

For EACH eval:
1. Read the rule file
2. Read relevant data
3. Apply rules
4. Produce result

Return results in this EXACT format:

EVAL: task_sequence
RESULT: PASS or FAIL
REASON: one sentence
FAILURE_MODE: (only if FAIL) standard_violation or format_violation
DETAILS: <relevant output fields>

(repeat for each eval)
```

## Step 4: Collect and Classify Results

After all 3 agents return:

1. Parse each agent's output to extract EVAL/RESULT/REASON/FAILURE_MODE/DETAILS blocks.
2. Compute overall score: `<pass_count>/19`.
3. For each FAIL, classify as **NET-NEW** or **RESOLVED** using this deterministic lookup:

   a. Read `joe/evals/traces/3_additional-items-to-change.md`. For each FAIL, attempt to match it to a known bug by eval name + failure description. If matched, note the bug identifier:
      - BUG-number bugs: extract the BUG-number from the Quick Reference table (e.g., BUG22, BUG32)
      - Named pattern bugs with no BUG-number: use `drying_format-all` for any drying_format FAIL, `BUG6-variant` for zero-count AFD rows in chamber tables

   b. Read `joe/evals/version_changelog.md`. Look up the bug identifier in the **Bug IDs Fixed** column:
      - Find the version where this identifier appears
      - Compare that version to the trace's pipeline version (use version ordering: V25 < V26 < V27 < V27.1 < V28 < V28.3 < V29 < V29.1 < V29.2 < V29.3)
      - Fix version > trace version → **RESOLVED (Vxx)** (e.g., RESOLVED (V29))
      - Fix version ≤ trace version, or identifier not found in any version → **NET-NEW**

   c. If no match found in additional-items-to-change.md → **NET-NEW** (newly discovered bug, not yet documented)

   d. If trace version is "unknown" → default all FAILs to **NET-NEW** (cannot determine if resolved)

   This is a deterministic lookup — do not use LLM judgment about whether descriptions "sound similar" to changelog entries. The match must be to a specific bug identifier in version_changelog.md.

4. For each FAIL, also classify as **Pipeline bug** or **Input quality**:
   - **Pipeline bug**: The pipeline could have done better with the given input (wrong category, dropped rooms, calculation errors, format violations, fabricated data).
   - **Input quality**: The input was insufficient (no tech notes, missing moisture data, photos from wrong rooms, no room IDs).

5. For each FAIL that is a pipeline bug, assign a **Priority**:
   - **CRITICAL**: IICRC/safety violations causing wrong output that could harm the job (wrong water category, wrong water class, mold/asbestos missed)
   - **HIGH**: Significant output errors (wrong mandatory tasks, wrong classification, dropped rooms, calculation errors)
   - **LOW**: Format/display issues, edge cases, minor inconsistencies

## Step 5: Write Trace Report

Write to `joe/evals/traces/trace_<first_8_chars_of_trace_id>.md`:

```
# Trace Evaluation: <trace_id>

**Date:** <trace_timestamp> | **Version:** <trace_version> | **Score:** <pass_count>/19
**Input:** <input_summary_one_line>

## Results

| # | Eval | Result | Priority | Type | Reason |
|---|------|--------|----------|------|--------|
| 1 | water_category | PASS/FAIL | --/CRITICAL/HIGH/LOW | --/NET-NEW/RESOLVED | reason |
| 2 | water_class | PASS/FAIL | ... | ... | ... |
...

## Failures

(For each FAIL, include a subsection:)

### <eval_name> [NET-NEW] or [RESOLVED]

**Priority:** CRITICAL/HIGH/LOW
**Failure Mode:** <mode>
**Assessment:** Pipeline bug / Input quality issue
**Node:** <pipeline node whose output demonstrates the violation — e.g., Description, Tasks, Equipment, Assembly>
**Details:** <details from agent>
```

## Step 6: Update INDEX.md (ALL Issues)

Read `joe/evals/traces/4_INDEX.md`. Update ALL FOUR sections:

### 6A: Add to Trace Log

Append a row to the **Trace Log** table at the bottom:

```
| <YYYY-MM-DD> | <trace_id_first_8> | <trace_version> | <pass_count>/19 | <comma_separated_list_of_ALL_failed_evals_or_"None"> |
```

If the trace already exists (re-evaluation), update the existing row.

### 6B: Update All Issues (Ranked by Frequency)

For EACH failed eval in this trace (whether NET-NEW or RESOLVED):

1. Check if this issue already exists in the **All Issues** table (match by eval name + similar reason/failure_mode).
2. If existing issue: increment Occurrences, append trace_id to Traces column.
3. If new issue: add a new row.

After updating, **re-sort the entire table by Occurrences descending** (most frequent at top) and **renumber the Rank column** sequentially.

Row format:
```
| <rank> | <one_line_issue_description> | <eval_name> | <priority> | <count> | <trace_id_first_8_list> | NET-NEW/RESOLVED | <bug_#_or_"--"> |
```

The **Priority** column reflects the highest priority seen for this issue across all traces: CRITICAL, HIGH, LOW, or -- (input quality).

The **Type** column reflects the current classification:
- If the issue is still present in the current pipeline version -> NET-NEW
- If the issue was fixed -> RESOLVED

The **Bug #** column links to additional-items-to-change.md issue number (if it's a pipeline bug), or "--" if it's an input quality issue.

### 6C: Recompute Summary Stats

Recompute and overwrite the **Summary** section at the top of INDEX.md using ALL rows in the Trace Log:

```
**Total:** <n> traces | **Avg Score:** <X.X>/19 (<pct>%) | **Last Updated:** <YYYY-MM-DD>
```

Recompute **Score Distribution** from all Trace Log rows:
- 19/19 (perfect): count and percentage
- 17-18 (minor): count and percentage
- 14-16 (moderate): count and percentage
- <14 (significant): count and percentage

### 6D: Append Full Report to INDEX.md

After updating the log table and All Issues table, append the complete trace report (from Step 5) as a new section at the bottom of INDEX.md.

1. If a `## Trace Reports` heading does not yet exist at the bottom of INDEX.md, add it.
2. Add a subsection for this trace: `### Trace: <trace_id_first_8> — <YYYY-MM-DD>`
3. Paste the full contents of `joe/evals/traces/trace_<id>.md` under that subsection.
4. If this trace was previously evaluated (re-run), replace the existing subsection rather than appending a duplicate.

## Step 7: Update changes-to-be-made.md (NET-NEW Pipeline Bugs Only)

For each FAIL that is BOTH **NET-NEW** AND a **pipeline bug** (not input quality):

1. Read `joe/evals/traces/5_changes-to-be-made.md`
2. Read `joe/evals/traces/3_additional-items-to-change.md` to find the highest existing BUG-number.
3. Check if the issue already exists in the Quick Reference table (match by eval name + failure mode + root cause)
4. If existing bug: add the trace_id to the existing bug's Traces column
5. If genuinely new bug (different root cause, not covered by any existing BUG-number):
   a. Assign next BUG-number (continuing from the highest found in additional-items-to-change.md, e.g., BUG33, BUG34, etc.)
   b. Add row to Quick Reference table
   c. Add detailed section below with Issue, Solution, Detail, and File subsections
6. Update the active bugs count at the top

Quick Reference row format:
```
| BUG<n> | CRITICAL/HIGH/LOW | <one_line_issue> | <one_line_fix> | <files> | <trace_ids> |
```

## Step 7B: Update implementation-plan.md (New Bugs Only)

For each **new BUG-number** created in Step 7 (not existing bugs that just got a trace added):

1. Read `joe/evals/traces/6_implementation-plan.md`
2. Add a row to the **Master Priority Table** with:
   - Priority: P0 (IICRC violation/safety = CRITICAL), P1 (incorrect output = HIGH), P2 (format/display = LOW), P3 (cosmetic/edge case = LOW)
   - BUG-number, issue summary, primary file, line reference (approximate), effort (Low/Medium/High), dependencies
3. Add a **detail section** at the end of the appropriate priority group with:
   - Issue (1 sentence)
   - Impact (1-2 sentences)
   - Root Cause (1-2 sentences identifying the specific code/prompt location)
   - Implementation steps (specific file changes with line references)
   - What changes (summary of files modified)
   - Dependencies (other bugs that should be fixed first or are related)
   - Verification (2-3 test scenarios)

This ensures every new BUG-number in changes-to-be-made.md has a corresponding implementation plan.

## Step 7C: Update all-issues.md

For each FAIL (whether NET-NEW or RESOLVED) from this /et run:

1. Read `joe/evals/traces/1_all-issues.md`
2. Check if the issue already exists (match by BUG# or eval name + failure mode)
3. If existing:
   - Add trace_id to the Traces list
   - Increment the trace count
   - If the issue was RESOLVED in this trace version: add a note "(re-occurrence in v<version>)" to the entry
4. If new issue: add an entry with source=ET, priority (CRITICAL/HIGH/LOW/-- for input quality), BUG# (if assigned in Step 7, else "--"), eval name, one-line summary, trace_id, and version found
5. Re-sort the table by trace count descending, then within equal counts by CRITICAL → HIGH → LOW

## Step 8: Display Summary

Reply in chat with a concise summary:

```
Trace <trace_id_first_8> evaluated: <pass_count>/19

NET-NEW: <list with priority or "None">
RESOLVED: <list or "None">
PASS: <count> evals passed

Report: joe/evals/traces/trace_<id>.md
INDEX updated: <n> issues tracked, <n> traces total
all-issues.md: <n> issues updated/added
```
