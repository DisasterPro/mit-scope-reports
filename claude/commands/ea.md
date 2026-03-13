# Eval All

Enhance trace evaluations with Claude-powered narratives, run 8 eval rules for bug detection, and log findings.

This is the Claude-side complement to the 30-minute `trace-eval.yml` GitHub Actions workflow. The workflow (in `EncircleInc/joe-sandbox`) does Python-based scoring and template narratives, committing results to joe-sandbox. This skill pulls the latest data via `gh api` (Step 0), then enhances it with AI narratives and rule-based bug detection.

## Arguments

`$ARGUMENTS` is optional. Defaults to enhancing all unprocessed traces.

## Document Flow

This skill writes to exactly TWO files:
1. `joe/evals/traces/2_scope-eval-all-runs.md` -- enhanced narratives + Bug Assessment sections + Bug Summary index + Bugs column
2. `joe/evals/traces/3_additional-items-to-change.md` -- rule violation bugs (BUG-numbers) + pipeline errors (PE-numbers)

Do NOT write to:
- `joe/evals/traces/4_INDEX.md` (only /et writes here)
- `joe/evals/traces/5_changes-to-be-made.md` (only /et writes here, uses BUG-numbers)
- `joe/evals/traces/6_implementation-plan.md` (only updated when changes-to-be-made.md is updated)

## Pipeline Reference

Agents MUST understand the pipeline before writing assessments or detecting bugs.

**DAG:** Description -> Merge -> RoomsWithId -> Tasks -> Equipment -> Drying -> Standards -> Assembly -> Translation

**LLM nodes (GPT-4.1):** Description.jinja2, Merge.jinja2, Tasks.jinja2, Drying.jinja2, PLXMatch.jinja2
**Python nodes:** RoomsWithId.py, Assembly.py, Equipment.py, Standards.py, PLXCandidates.py, PLXAssembly.py

**Node responsibilities:**
- **Description**: Extracts rooms, damage, materials, water source/category/class from photos + notes. First LLM in the chain.
- **Merge**: Consolidates room data from multiple sources (app, notes, floor plans). Deduplicates materials, resolves conflicts between sources.
- **RoomsWithId**: Assigns stable IDs. Reconstructs rooms from floor plans. Filters organizational rooms (documentation, checklists, media rooms).
- **Tasks**: Generates IICRC-sequenced task lists per room based on damage type, materials, and category. Includes antimicrobial, carpet lift, bio-wash rules.
- **Equipment**: Calculates drying equipment (dehumidifiers, air movers, AFDs) based on room SF, class, and materials.
- **Drying**: Formats drying chamber assignments and equipment placement tables.
- **Assembly**: Renders final scope document with room sections, task tables, materials, and estimate.
- **Translation**: Handles language output (English/French).

**Key behaviors:**
- Rooms come from 3 sources: app setup, technician notes, floor plans
- Floor plan room names must match claim room names for measurements to be assigned
- Organizational rooms (e.g., "Initial Visit", "Cause of Loss", "Data", "Checklist", "Photo", "Video") should never be marked affected
- Water category follows IICRC S500 10.4.1 (fixture-specific, not generic labels)
- Task sequence: content protect -> extract -> remove -> clean -> antimicrobial -> dry
- Equipment sizing: based on room SF, class, materials (not guessed)
- All LLMs run at temperature=1 (OpenAI default, no override)
- Category 2-3 requires containment; Cat 1 only gets carpet lift and single antimicrobial; Cat 3 gets bio-wash and double antimicrobial

**Rules for all agents:**
- MUST read relevant rule files from `joe/evals/rules/` before writing
- MUST NOT reference internal node names (Assembly, Merge, RoomsWithId, etc.) in user-facing narrative text -- use "the system", "the scope", "the pipeline"
- MUST NOT speculate about causes -- only state what the data shows
- MUST NOT mention cost, pricing, or PLX/estimating in any output

## Step 0: Pull Latest Data

Run `joe/scripts/pull-reports.sh` via Bash to fetch the latest scope-eval-all-runs.md from joe-sandbox. This uses `gh api` to read from the private EncircleInc/joe-sandbox repo (no PAT needed -- uses the codespace's gh auth). The script merges new GitHub data while preserving locally enhanced traces (Bug Assessment sections survive the merge).

If the pull fails (e.g., gh not authenticated, network error), log the warning and continue with existing local data -- stale data is better than no data.

## Step 1: Check for New Traces

1. Read the local file: `joe/evals/traces/2_scope-eval-all-runs.md` (refreshed by Step 0)
2. Identify traces that have template narratives (not yet enhanced). Template narratives use formulaic patterns:
   - Input Assessment starts with "X field photos were submitted" or "X photos were submitted"
   - Pipeline Assessment starts with "The scope completed successfully in"
   - Recommendations say "This scope had good input data" or are single generic items
3. Also check for traces missing a `### Bug Assessment` section (not yet bug-checked).
4. If all traces are enhanced and bug-checked, reply: "All traces are up to date. No new work needed."

## Step 2: Enhance Template Narratives

For each trace with template narratives:

1. Extract the trace ID from the section header (32-char hex string).
2. Fetch the trace from Langfuse: call `mcp__langfuse__fetch_trace` with the trace_id.
3. Call `mcp__langfuse__fetch_observations` for the trace to get pipeline node outputs.
4. If needed, call `mcp__langfuse__fetch_observation` for specific nodes (Description, Merge, RoomsWithId, Tasks, Equipment, Assembly) to get detailed data.

**Verify and correct template stats against Langfuse data:**

The GitHub Actions workflow sometimes fetches traces before Langfuse has fully populated them, resulting in wrong counts (e.g., 0 floor plans when 2 exist, "unknown" version when version is known, wrong room counts). After fetching the trace from Langfuse, verify these fields and correct the template if they differ:

- **Version**: Compare template header version with `trace.metadata.version`. If template says "unknown" but Langfuse has a version, update the header.
- **Floor Plans**: Compare template `**Floor Plans:** N` with `len(trace.input.measurement_images)`. If mismatched, correct.
- **Photos**: Compare template `**Photos:** N` with `len(trace.input.property_images)`. If mismatched, correct.
- **Notes**: Compare template `**Notes:** N` with count of `<NOTE>` blocks in `trace.input.description`. If mismatched, correct.
- **Rooms**: Compare template `**Rooms:** N total (A affected, U unaffected)` with RoomsWithId output room count. If mismatched, correct.
- **Index row**: If ANY of the above changed, also update the corresponding index table row to match.

This verification is critical because stale template data cascades into wrong narratives, wrong bug assessments, and wrong skip decisions.

**Update the section header** to include trace run time:
- Current: `## <trace_id> -- YYYY-MM-DD -- version`
- New: `## <trace_id> -- YYYY-MM-DD HH:MM UTC -- version`
- **CRITICAL:** The HH:MM UTC time MUST come from the Langfuse trace `timestamp` field (when the scope actually ran in production). Do NOT use the current time, the enhancement time, or the sync time. The Langfuse timestamp is the authoritative source. Parse the timestamp from the Langfuse API response and convert to UTC if needed. The time shown in scope-eval-all-runs.md must match what Langfuse displays for that trace.

**Update the What Was Provided table** -- full 11-row set, always in this order:

```
| Category | Status | Details |
|----------|--------|---------|
| Structures | Clean/Mixed/Org-heavy | 12 total; 8 real rooms, 4 organizational (Initial Visit, Cause of Loss, Data, Checklist) |
| Room Setup | Good | 5 rooms; 5 in app, 3 from notes |
| Field Photos | Good | 40 photos; 0 rooms without photos |
| Technician Notes | Detailed | 6 notes; 5 with rooms, 1 without rooms |
| Video Transcripts | 3 found | 3 room video transcripts |
| Thermal Images | None | 0 thermal/FLIR/IR images detected |
| 360 Photos | None | 0 panoramic/360° images detected |
| Floor Plans | None | 0 plans; 0 rooms with measurements |
| Room Name Matching | N/A | 0 unmatched floor plan rooms |
| Moisture Data | None | -- |
| Guidelines | None | -- |
```

Row definitions (detect from Langfuse trace data):

- **Structures** -- All structures (rooms + org items) submitted in the job. Status: `Clean` (all real rooms), `Mixed` (some org items present), `Org-heavy` (majority org items). Details: `X total; Y real rooms, Z organizational (list org item names)`. Org patterns: "Initial Visit", "Cause of Loss", "Data", "Checklist", "Documentation", "Admin", "Photo", "Video".
- **Room Setup** -- Rooms configured in app vs rooms found in tech notes. Status: `Good` (all rooms set up), `Partial` (some missing), `Poor` (few set up). Details: `X rooms; Y in app, Z from notes`.
- **Field Photos** -- Photo coverage across rooms. Status: `Good` (all rooms have photos), `Partial` (some without), `None` (no photos). Details: `X photos; Y rooms without photos`.
- **Technician Notes** -- Written notes only (NOT video transcripts). Count `<NOTE>` tags in trace.input.description. Status: `Detailed` (3+ notes, good coverage), `Adequate` (some notes), `Limited` (1-2 notes), `None` (0 notes). Details: `X notes; Y with rooms, Z without rooms` where Z = orphan notes not attached to any room structure.
- **Video Transcripts** -- Room video transcripts. Count `<ROOM_VIDEO>` tags in trace.input.description. Status: `N found` or `None`. Details: `X room video transcripts`. Update the header `**Notes:** N` to reflect `<NOTE>` count only (not `<NOTE>` + `<ROOM_VIDEO>`).
- **Thermal Images** -- Scan `trace.input.property_images` filenames/metadata for: "thermal", "FLIR", "IR", "infrared", "heat". Status: `N found` or `None`. Details: count detected.
- **360 Photos** -- Scan `trace.input.property_images` for: "360", "pano", "panoramic", "equirectangular", "sphere". Status: `N found` or `None`. Details: count detected.
- **Floor Plans** -- Measurement images count. Status: `Good` (present), `None`. Details: `X plans; Y rooms with measurements`.
- **Room Name Matching** -- Floor plan room names vs claim room names. Status: `Good`, `Issues`, `N/A` (no floor plans). Details: `X unmatched floor plan rooms`.
- **Moisture Data** -- Moisture readings in input. Status: `Present` or `None`. Details if present.
- **Guidelines** -- User guidelines/instructions. Status: `Present` or `None`. Details if present.

**Rewrite the four narrative sections:**

### Input Assessment (1-2 paragraphs)
- What was provided and how well organized
- Specific gaps (rooms without photos, rooms without notes, etc.)
- Room name matching issues if any (floor plan names vs claim names)
- Note if structures include organizational items that aren't real rooms
- Be specific about THIS trace's data, not generic

### Pipeline Assessment (1 paragraph)
- Processing time and whether it completed successfully
- Any data quality issues the system detected (missing measurements, photo-damage mismatches, organizational rooms)
- Note if organizational structures were correctly filtered or incorrectly scoped
- Do NOT mention cost or pricing

### Issue Assessment (1-2 paragraphs)
- Summarize each data quality issue found (standard violations, material conflicts, scope conflicts, equipment sizing issues, missing measurements)
- Group by type and describe in plain language
- Distinguish between input-caused issues and system-caused issues
- If no issues found, say "No data quality issues were detected."

### Recommendations (numbered list, 3-5 items)
- Specific to THIS scope's gaps (not generic advice)
- Written for a field technician, plain language
- Explain WHY each step matters
- Do NOT mention cost, pricing, or internal system names
- **Floor plan + room mismatch rule:** Any time a floor plan is included but room names could not be matched (unmatched floor plan rooms > 0, or measurements not assigned), ALWAYS include a recommendation to verify that floor plan room names match the claim room names before running the scope. Explain that mismatched names prevent the system from assigning measurements to rooms.

**Important:** Keep the scores line and metadata unchanged. Only rewrite the header (add time), What Was Provided table (add Structures row), and the four narrative sections.

## Step 3: Bug Detection

For each trace that doesn't have a `### Bug Assessment` section yet:

**Skip condition:** If Input Quality < 3/5, skip bug assessment. Write: `**Rules Checked:** 0/8 | Skipped (insufficient input data)`

**For eligible traces (Input >= 3/5):**

1. Use the Langfuse data already fetched in Step 2.
2. Launch **2 agents in parallel**:

**Agent A -- Classification + Rooms (4 rules):**
Read these rule files before evaluating:
- `joe/evals/rules/water_category.md`
- `joe/evals/rules/water_class.md`
- `joe/evals/rules/room_integrity.md`
- `joe/evals/rules/hallucination.md`

Data needed: input description, Description output, Merge output, RoomsWithId output, final scope.

**Agent B -- Tasks + Equipment (4 rules):**
Read these rule files before evaluating:
- `joe/evals/rules/task_sequence.md`
- `joe/evals/rules/equipment.md`
- `joe/evals/rules/task_tense.md`
- `joe/evals/rules/material_room_integrity.md`

Data needed: Description output, Merge output, Tasks output, Equipment output, Drying output, final scope.

**Each agent must:**
- Read the rule file FIRST
- Apply rules to the actual trace data
- Return for each rule: RULE_NAME, RESULT (PASS or **FAIL**), DETAILS (one sentence explaining the violation or "--" for PASS)
- Only flag **FAIL** when the pipeline output clearly violates the rule. Data quality gaps (missing photos, missing notes) are NOT bugs.

3. Write the Bug Assessment section after Recommendations. Assign EA numbers (EA-1, EA-2, ...) sequentially within the trace for each FAIL. PASS rows use `--` in the EA # column.

**Priority rules:**
- **CRITICAL** = safety/IICRC violation causing wrong output (e.g., water_category wrong -- could cause mold)
- **HIGH** = significant output error (e.g., missing mandatory task, wrong class)
- **LOW** = format/display issue

```markdown
### Bug Assessment

| EA # | Rule | Priority | Result | Node | Details |
|------|------|----------|--------|------|---------|
| EA-1 | water_category | HIGH | **FAIL** | Description | Toilet overflow classified as Cat 1; should be Cat 2 per S500 10.4.1 |
| -- | water_class | -- | PASS | -- | -- |
| -- | room_integrity | -- | PASS | -- | -- |
| -- | hallucination | -- | PASS | -- | -- |
| -- | task_sequence | -- | PASS | -- | -- |
| -- | equipment | -- | PASS | -- | -- |
| -- | task_tense | -- | PASS | -- | -- |
| -- | material_room_integrity | -- | PASS | -- | -- |
```

**Node column**: For each FAIL, identify which pipeline node's output demonstrates the violation (e.g., `Description`, `Tasks`, `Equipment`, `Assembly`). Use `--` for PASS rows.

If no bugs: `**Rules Checked:** 8/8 | **Bugs Found:** 0` then "No rule violations detected."

4. Update the index table `Bugs` column for this trace: `0/8`, `2/8`, etc. (or `skip` for skipped traces).

5. For each **FAIL** found, update `joe/evals/traces/3_additional-items-to-change.md`:
   - Read the file, check if the same rule violation already exists (match by rule + similar root cause)
   - **If existing bug:** Add the trace_id to the existing entry's Traces column in the Quick Reference table. Do NOT add a duplicate detail section below -- the existing detail section covers the bug. If new trace adds meaningful context (e.g., different time values, different room names), append a brief note to the existing detail section's Traces line.
   - **If genuinely new bug** (different rule or fundamentally different root cause): Assign next BUG-number, record the EA# alongside it, add to Quick Reference table, add ONE detailed section below.
   - **Reconciliation rule:** Multiple traces with the same underlying bug = ONE BUG entry with multiple trace IDs. The Quick Reference Traces column shows all affected trace IDs (comma-separated). The detail section below explains the bug once with all trace IDs listed. Update the Trace Count accordingly.
   - **Quick Reference table columns:** `| BUG # | EA # | Priority | Rule | Summary | Trace Count | Traces |`
   - **Update `joe/evals/traces/1_all-issues.md`:** For each FAIL, add or update the issue entry with: source=EA, EA#, BUG#, priority, trace_id, version, status.

## Step 4: Pipeline Error Check

Review each new trace for PIPELINE errors (separate from rule violation bugs):

Pipeline errors are:
- Node failures: a pipeline node crashed or returned null
- Data flow breaks: data present in one node but lost/corrupted in a later node
- Observation errors: Langfuse shows ERROR level on a node

Do NOT flag as pipeline errors:
- Missing user input (photos, notes, floor plans, moisture data, rooms not set up)
- Rule violations (those are BUGs from Step 3)

For each pipeline error found, update `joe/evals/traces/3_additional-items-to-change.md`:
1. Check if the error already exists (match by node + description)
2. If new: assign next PE-number (PE1, PE2, ...), add to Pipeline Errors Quick Reference, add detailed section
3. If existing: add the trace_id to the existing entry

## Step 5: Write Results

1. Update `joe/evals/traces/2_scope-eval-all-runs.md`:
   - Enhanced narratives replacing template text
   - Updated headers with **Langfuse trace timestamp** (NOT enhancement/sync time)
   - Structures row in What Was Provided tables
   - Bug Assessment sections
   - Updated index table Bugs column values
2. Update `joe/evals/traces/3_additional-items-to-change.md` if BUGs or PEs were found.
3. **Update the Bug Summary section** at the top of `joe/evals/traces/2_scope-eval-all-runs.md`:
   - Located between the header stats line and the `## Index` section
   - Rebuild the Bug Summary table from the current state of `additional-items-to-change.md`
   - Include columns: `| BUG # | EA # | Priority | Rule | Summary | Trace Count |`
   - Update Trace Count for each bug (count trace IDs in the Traces column)
   - Update the "By Rule" and "By Priority" summary lines
   - This ensures the Bug Summary always reflects the latest bug state

## Step 6: Summary

Display a concise summary:

```
## Eval All Summary

**Processed:** {n} traces enhanced, {n} bug-checked
**Bugs Found:** {n} total ({n} new BUG-numbers, {n} added to existing)
**Pipeline Errors:** {n} found ({n} new PE-numbers, {n} added to existing)

| Trace | Date | Input | Pipeline | Issues | Bugs | Overall | New Findings |
|-------|------|-------|----------|--------|------|---------|-------------|
| {id_8} | {date} | {score} | {score} | {score} | {x/8} | {score} | {list or "None"} |
...
```
