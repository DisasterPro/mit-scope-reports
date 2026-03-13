# Scope Error Report

Generate an ad-hoc production scope error analysis report using Langfuse trace and observation data.

**Note:** Daily and weekly error reports are generated automatically by GitHub Actions (`EncircleInc/joe-sandbox`) and synced to `joe/docs/reports/scope-errors.md`. Use this skill only for ad-hoc queries with custom time ranges.

## Arguments

`$ARGUMENTS` is the time period. Parse it as follows:
- Format: number + unit, where unit is `d` (days) or `h` (hours). Examples: `7d`, `24h`, `3d`, `12h`
- Default (if blank or missing): `7d`
- Convert to minutes: days * 1440, hours * 60
- Maximum: 10080 minutes (7 days -- the Langfuse API limit)
- If the requested period exceeds 7 days, cap at 10080 and note the cap in the report

## Execution Strategy

Use a **single subagent** (Agent tool, subagent_type="general-purpose") to perform ALL data collection (Steps 1-4). This keeps the large Langfuse API responses out of the main conversation context. The subagent prompt should contain these instructions verbatim.

After the subagent returns its structured summary, write the report (Step 5) in the main conversation.

## Step 1: Fetch Production Traces and Count Totals

Paginate through ALL traces using `mcp__langfuse__fetch_traces`:
- `age`: the calculated minutes
- `limit`: 100
- `page`: 1, 2, 3, ... until a page returns fewer than 100 items

For each trace on each page, extract ONLY these fields (ignore input/output blobs):
- `id`
- `environment` (from trace object or metadata.resourceAttributes)
- `name`
- `output` -- ONLY check if it is `null` or not. Do NOT read the content.
- `userId`
- `timestamp`
- `totalCost`
- `latency`

**Filter:** Include only traces where `environment` equals `"production"` AND `name` is NOT `"experiment-item-run"`.

**Count:** Total production traces (denominator) and traces where `output` is `null` (candidate errors).

**IMPORTANT -- False positives:** The Langfuse compact response mode sometimes truncates `output` to appear null when it is actually present. For EVERY candidate error trace (output=null in the list), call `mcp__langfuse__fetch_trace` with `trace_id` and `include_observations=false` to verify the output is truly null. Only confirmed null-output traces are errors.

## Step 2: Fetch Observations for Confirmed Error Traces

For each confirmed error trace, fetch its observations to find the root cause:

Call `mcp__langfuse__fetch_observations` with:
- `age`: same minutes value
- `trace_id`: the error trace's `id`
- `limit`: 100
- `output_mode`: `compact`

Find the **primary error observation**: one where:
- `level` equals `"ERROR"`
- `name` is NOT `"flow"`, `"PromptFlowExecutor.exec"`, or `"POST /v1/mitigation-scopes"` (these are cascading error propagation, not the root cause)

From the primary error observation extract:
- `name`: the failing pipeline node (Description, Merge, Drying, Tasks, Equipment, etc.)
- `statusMessage`: the error details

**For ContentFilter errors:** The statusMessage on the ERROR observation usually shows "content_filter" or "Premature completion" but does NOT specify which filter triggered. To get the specific filter type, find the corresponding `openai_chat` or `openai_chat_async` SPAN (level=DEFAULT) with the same `node_name` in its metadata. Its `output.choices[0].content_filter_results` will show which filter has `"filtered": true`:
- `"sexual": {"filtered": true}` -> Sexual
- `"self_harm": {"filtered": true}` -> Self-Harm
- `"violence": {"filtered": true}` -> Violence
- `"hate": {"filtered": true}` -> Hate
- `"profanity": {"filtered": true}` -> Profanity
- If the error is `BadRequestError: 400 - content_filter` (prompt-level rejection, no response generated), classify as "Prompt Rejected"

**Pipeline Completeness Analysis (for all error traces):**

For each error trace, determine which pipeline nodes completed by checking observation names. The expected node order is:
1. Description (LLM)
2. PropertyImages (LLM, parallel)
3. MeasurementImages (LLM, parallel)
4. PropertyImagesAggregator (Python)
5. MeasurementImagesValidator (Python)
6. RoomNameNormalizer (Python)
7. Merge (LLM)
8. RoomsWithId (Python)
9. Tasks (LLM)
10. Equipment (Python)
11. Standards (Python)
12. Drying (LLM)
13. Assembly (Python)
14. Translation (LLM, optional)

Record: `last_completed_node`, `nodes_completed_count`, `pipeline_complete` (true if Assembly or Translation has an observation with output).

For traces where no ERROR observation is found, apply Step 2B heuristics instead of classifying as "Unknown".

## Step 2B: Classify "Unknown" Traces Using Metadata Heuristics

For traces where Step 2 found NO primary error observation (would otherwise be "Unknown"), apply these heuristics IN ORDER (first match wins):

### Heuristic 1: Assembly Framework Error
**Condition:** ALL pipeline nodes have observations (Assembly or Translation present) but trace output is null.
**Classification:** `AssemblyFrameworkError`
**Failing Node:** Assembly

### Heuristic 2: Timeout / Rate Limit
**Condition:** Trace latency > 300 seconds (5 minutes).
**Classification:** `Timeout`
**Failing Node:** last_completed_node

### Heuristic 3: Infrastructure Incident (Temporal Cluster)
**Condition:** 3 or more unclassified error traces occur within a 30-minute window.
**Classification:** `InfrastructureIncident`
**Failing Node:** varies

### Heuristic 4: Image Processing Stall
**Condition:** Last completed node is PropertyImages, PropertyImagesAggregator, MeasurementImages, or MeasurementImagesValidator (pipeline stalled during image processing phase).
**Classification:** `ImageProcessingError`
**Failing Node:** the last image processing node that ran

### Heuristic 5: Early Pipeline Stall
**Condition:** Only Description node completed (or fewer), AND latency < 300s.
**Classification:** `EarlyPipelineError`
**Failing Node:** last_completed_node or Description

### Heuristic 6: Mid-Pipeline Data Error
**Condition:** Pipeline stalled at a Python data node (RoomNameNormalizer, RoomsWithId, Equipment, Standards).
**Classification:** `DataProcessingError`
**Failing Node:** the stalled Python node

### Heuristic 7: Fallback
**Condition:** None of the above matched.
**Classification:** `Unknown`
**Note:** Include pipeline_completeness and last_completed_node in the report for manual investigation.

## Step 3: Classify and Return Summary

Return a structured summary with:

1. **Totals:** total_production_traces, total_error_traces, error_rate_pct
2. **Error list:** For each error trace:
   - trace_id, userId, timestamp (date only), totalCost, latency
   - error_type: ContentFilterCompletion, ValueError, AttributeError, TemplateSyntaxError, AssemblyFrameworkError, Timeout, InfrastructureIncident, ImageProcessingError, EarlyPipelineError, DataProcessingError, Unknown, or Other
   - failing_node: the pipeline node name
   - filter_type: (for content filter only) Sexual, Self-Harm, Violence, Hate, Profanity, Prompt Rejected, or Unknown
   - statusMessage excerpt (first 200 chars)
   - pipeline_completeness: which nodes completed, last_completed_node

## Step 4: Write the Report

Append this run's report to the running log at `joe/docs/reports/scope-errors.md`. Do NOT overwrite existing content.

### 4A: Determine Section

Classify the period into one of three sections:
- **Weekly**: period is 7d or 10080 minutes
- **Daily**: period is 1d or 24h or 1440 minutes
- **Other**: any other period (3d, 12h, etc.)

### 4B: Build the Entry

Format the new report entry as:

```
### YYYY-MM-DD | Period: <period>

**Generated:** YYYY-MM-DD HH:MM UTC | **Scopes:** <count> | **Errors:** <count> (<pct>%) | **Error Rate:** <pct>%

#### Errors by Type

| Error Type | Node | Traces | Filter |
|---|---|---|---|
| ContentFilterCompletion | Description | <n> | Sexual |
| ContentFilterCompletion | Merge | <n> | Profanity |
| ... | ... | ... | ... |
| **Total** | | **<n>** | |

#### Error Details

##### ContentFilterCompletion (<count> traces)

**Impact:** Complete scope failure -- Azure content safety filter truncated the LLM completion output
**Root Cause:** The LLM response contained content that triggered Azure's content filter, causing `finish_reason: "content_filter"` instead of `"stop"`. The pipeline treats this as a `CompletionException` and fails the entire scope.

| Trace ID | Date | User | Node | Filter Type |
|---|---|---|---|---|
| <trace_id> | <date> | <user> | <node> | <filter_type> |
...

---

##### Timeout (<count> traces)

**Impact:** Complete scope failure -- pipeline execution exceeded time limit.
**Root Cause:** Azure rate limiting with retry backoff, large/complex input, or HTTP timeout. Traces with >$2.00 cost likely hit rate limits repeatedly before timing out.

| Trace ID | Date | User | Latency | Cost | Last Node |
|---|---|---|---|---|---|
...

---

##### InfrastructureIncident (<count> traces)

**Impact:** Multiple scope failures in short window -- service-level disruption.
**Root Cause:** Service Bus connection loss, Azure regional degradation, pod restart, or OOM. Clustered timing distinguishes from individual failures.

| Trace ID | Date | User | Time (UTC) | Last Node |
|---|---|---|---|---|
...

---

##### AssemblyFrameworkError (<count> traces)

**Impact:** Complete scope failure -- all pipeline nodes ran but final output is null.
**Root Cause:** Assembly node completed without exception but produced null/malformed output, or response serialization failed after PromptFlow trace closed.

| Trace ID | Date | User | Cost |
|---|---|---|---|
...

---

##### ImageProcessingError (<count> traces)

**Impact:** Complete scope failure -- pipeline stalled during image analysis phase.
**Root Cause:** Azure Vision API failure, rate limit, or image validation error during PropertyImages or MeasurementImages processing.

| Trace ID | Date | User | Stalled At |
|---|---|---|---|
...

---

##### EarlyPipelineError (<count> traces)

**Impact:** Complete scope failure -- pipeline failed at or before Description node.
**Root Cause:** Input validation failure, malformed request, or Description output missing required fields.

| Trace ID | Date | User | Last Node |
|---|---|---|---|
...

---

##### DataProcessingError (<count> traces)

**Impact:** Complete scope failure -- Python node encountered unexpected data.
**Root Cause:** Type mismatch, missing field, or unexpected input shape in a Python processing node. Error caught internally without ERROR-level Langfuse observation.

| Trace ID | Date | User | Stalled At |
|---|---|---|---|
...

---

##### <OtherErrorType> (<count> traces)

**Impact:** Complete scope failure
**Node:** <node_names>
**Message:** `<representative_error_message>`
**Root Cause:** <brief technical analysis>

| Trace ID | Date | User |
|---|---|---|
...

(Repeat for each error type, sorted by trace count descending)

#### Affected Users

| User | Error Count | Error Types |
|---|---|---|
...

---
```

Format percentages to 1 decimal place. Sort error types by trace count descending. Sort affected users by error count descending.

### 4C: Insert Into File

Read `joe/docs/reports/scope-errors.md`. If the file does not exist, create it with this skeleton first:

```
# Scope Error Report

## All-Time Summary

*Updated from most recent report.*

| Metric | Last Value |
|---|---|
| Total Production Scopes | — |
| Traces with Errors | — |
| Total Error Observations | — |
| Content Filter Errors | — |
| Pipeline Errors | — |

---

## Weekly Reports (7d)

## Daily Reports (24h)

## Other Reports
```

Then insert the new entry **immediately after** the matching section header line (e.g., after `## Weekly Reports (7d)`) as the first entry in that section, above any prior entries. Preserve all existing content below. The result is most-recent-first ordering within each section.

**Update All-Time Summary.** After inserting, replace the table under `## All-Time Summary` with the new report's summary values (Total Production Scopes, Traces with Errors count/pct, Total Error Observations, Content Filter Errors, Pipeline Errors).

Root cause analysis guidance:
- ContentFilterCompletion: Azure content safety filter truncated the LLM completion output. The LLM response contained content that triggered the filter, causing the entire node to fail. Common triggers: Sexual filter on water damage descriptions involving bedrooms/bathrooms, Self-Harm filter on water damage descriptions mentioning basement/injury scenarios, Violence filter on fire damage descriptions.
- TemplateSyntaxError: Jinja2 template rendering failed in Assembly.py. Identify the template issue from the error message.
- AttributeError: Python type mismatch. Note the specific attribute and expected type from the message.
- ValueError: Validation error in a Python node. Note the specific validation constraint from the message.
- AssemblyFrameworkError: All pipeline nodes completed but output is null. Assembly produced malformed output or response serialization failed after the PromptFlow trace closed.
- Timeout: Pipeline exceeded 300s execution time. Common causes: Azure rate limiting with retry backoff, large input with many rooms/images, or HTTP request timeout.
- InfrastructureIncident: Multiple failures clustered within 30 minutes. Indicates service-level disruption rather than individual trace issues.
- ImageProcessingError: Pipeline stalled during image analysis phase (PropertyImages or MeasurementImages). Azure Vision API failure, rate limit, or image validation error.
- EarlyPipelineError: Pipeline failed at or before Description node. Input validation failure, malformed request data, or Description output missing required fields.
- DataProcessingError: Pipeline stalled at a Python data node. Type mismatch, missing field, or unexpected input shape caught internally without ERROR observation.

**NOTE:** The Langfuse `get_error_count`, `find_exceptions`, and `get_exception_details` APIs do NOT work for this service's error type. Our errors are recorded as ERROR-level observations, not as Langfuse exception events. Do not use those APIs.
