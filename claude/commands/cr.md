# Change Review

Review a proposed change to the mitigation scope pipeline before implementation. Reads the relevant flow files, runs tests, checks which eval rules are impacted, and produces a structured change assessment.

This is "plan mode on steroids" for mit scope -- specialized knowledge of the pipeline, eval rules, test suite, and known bug history.

## Usage

`/cr <description of proposed change>`

Arguments: `$ARGUMENTS` (natural language description of what you want to change and why)

## Process

### Step 1: Parse the Proposed Change

Extract from `$ARGUMENTS`:
- **What**: Which file(s) and which logic would change (if known)
- **Why**: The problem being solved or feature being added
- **Scope**: Which part of the pipeline (Description, Merge, RoomsWithId, Tasks, Equipment, Assembly, Drying, other)

If the proposed change is vague, ask one clarifying question before continuing.

### Step 2: Read Relevant Flow Files

Based on the proposed change scope, read the relevant files from `src/mitigation_scope/flow/`:

**Prompt/template files (Jinja2):**
- `Description.jinja2` -- water category/class, source of loss, room descriptions, fixture detection
- `Merge.jinja2` -- merges room descriptions with structural data
- `Tasks.jinja2` -- task generation, sequencing, tense conventions, materials
- `Equipment.jinja2` (note: Equipment uses `Equipment.py` not a jinja2 file -- use the .py)
- `Drying.jinja2` -- drying placement notes, chamber tables, equipment placement

**Python files:**
- `RoomsWithId.py` -- room deduplication, org room filtering, fire override logic
- `Equipment.py` -- IICRC equipment calculations, air movers, dehumidifiers, AFD
- `Assembly.py` -- final scope assembly, table formatting, material room integrity
- `Standards.py` -- IICRC standards constants and helpers

**Schema:**
- `flow.dag.yaml` -- DAG node definitions and connections

Read the full file if it's the primary target, or grep for the specific function/section if it's large.

### Step 3: Run Current Tests

Run the test suite to establish a baseline:

```bash
cd /workspaces/ai-services/services/mitigation-scope && poetry run pytest tests/ -x -v --tb=short 2>&1 | tail -40
```

Report:
- Total tests: X passing, Y failing
- Any pre-existing failures (important context -- don't confuse existing failures with regressions)
- Relevant test files for the proposed change area

### Step 4: Check Eval Rule Impact

Read the eval rules that could be affected by this change. Cross-reference with:
- `joe/evals/rules/` -- all 19 rule files organized by what they check
- `joe/evals/version_changelog.md` -- see if this area has been buggy before

**Rule-to-pipeline mapping:**

| Eval Rule | Checks | Affected By Changes To |
|-----------|--------|----------------------|
| water_category | Cat 1/2/3 from fixture/source | Description.jinja2 fixture table, source detection |
| water_class | Class 1-4 from evaporation load | Description.jinja2 class logic |
| room_integrity | Rooms flow through system correctly | RoomsWithId.py, Merge.jinja2, Assembly.py |
| hallucination | No fabricated data | Tasks.jinja2, Equipment.py, Assembly.py |
| task_sequence | Correct task ordering + mandatory tasks | Tasks.jinja2 |
| task_tense | Present/past tense, dedup, Scenario A/B/C | Tasks.jinja2 |
| equipment | IICRC air mover / dehumidifier counts | Equipment.py |
| material_room_integrity | Materials scoped to correct rooms | Assembly.py, Tasks.jinja2 |
| material_consistency | Consistent material references | Tasks.jinja2, Assembly.py |
| narrative_consistency | Consistent narrative across sections | Merge.jinja2, Assembly.py |
| drying_format | Drying table format correctness | Drying.jinja2 |
| standards_display | IICRC section numbers correct | Description.jinja2, any node |
| measurement_integrity | Area/perimeter/volume math | RoomsWithId.py, Equipment.py |
| math_calculations | Arithmetic correct | Equipment.py, Assembly.py |
| job_type | Job type detection correct | Description.jinja2 |
| mold_fire | S520/S700 classification | Description.jinja2, Tasks.jinja2 |
| asbestos_lead | EPA compliance detection | Description.jinja2, Tasks.jinja2 |
| iicrc_references | Section numbers not fabricated | Any node |
| emergency_services | Tarping/board-up only when explicit | Tasks.jinja2, Description.jinja2 |
| data_quality | Input quality tracking | Description.jinja2, Merge.jinja2, RoomsWithId.py |

For each impacted rule, read its rule file (`joe/evals/rules/{rule}.md`) and check whether the proposed change could cause new failures.

**Invoke eval-impact agent** (`.claude/agents/eval-impact.md`) with the change description and file list to get a structured risk table.

### Step 4.5: Invoke Specialist Agents

Based on which files are changing, invoke the appropriate specialist agents from `.claude/agents/`:

| If changing... | Invoke |
|----------------|--------|
| `flow.dag.yaml` | `schema-validator.md` |
| Any `.py` in `src/mitigation_scope/flow/` | `py-logic-reviewer.md` |
| Any `.jinja2` in `src/mitigation_scope/flow/` | `prompt-logic-reviewer.md` |
| Category/class logic, equipment calcs, task sequences | `domain-expert.md` |
| After implementing (not during review) | `bug-agent.md` |
| Any change affecting output format or docs | `doc-updater.md` |

Run agents in parallel where independent. Each agent reads the relevant files and returns a verdict (APPROVE / APPROVE WITH NOTES / NEEDS FIX).

### Step 5: Check Bug History

Read `joe/evals/traces/5_changes-to-be-made.md` and `joe/evals/version_changelog.md`:
- Are there open bugs in this area?
- Has this area been changed before and caused regressions?
- Are there B-numbers that this change might fix or break?

### Step 6: Produce Change Review

Output a structured review:

```markdown
## Change Review: {one-line summary}

**Proposed:** {what and why}
**Files Affected:** {list}

---

### Current Test Status
{X passing, Y failing -- brief baseline}

### Eval Rules at Risk
| Rule | Risk | Reason |
|------|------|--------|
| {rule} | HIGH/MED/LOW | {why this change could affect it} |

### Known Bug History in This Area
{List any open B-numbers or past regressions, or "No known issues"}

### Implementation Guidance
{Specific notes about the change: what to watch out for, which line numbers / functions are most relevant, edge cases}

### Recommended Test Cases
{2-4 specific test scenarios to verify after implementing the change}

### Confidence Assessment
**Confidence:** HIGH / MEDIUM / LOW
**Reason:** {Why this confidence level}
{If LOW or MEDIUM: specific concerns that should be addressed before or during implementation}
```

## Notes

- This skill does NOT implement the change -- it reviews and plans
- After review, use normal Claude Code editing to implement
- After implementing, run `/fv` on any affected traces to validate
- If tests fail after change, run pytest on the specific failing test file first before debugging broadly
- Never skip tests when making changes to Equipment.py, RoomsWithId.py, or Assembly.py -- these have the most complex logic
