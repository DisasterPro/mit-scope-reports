# Trace Review

Technical per-node breakdown of a Langfuse trace. Shows each pipeline node's timing, token usage, status, and key output characteristics. Responds in chat only -- does not write to any files.

## Arguments

`$ARGUMENTS` is the trace_id. It may be a full Langfuse URL or just the ID string. Extract the trace ID (hex string).

## Step 1: Fetch Trace

Call `mcp__langfuse__fetch_trace` with trace_id, `include_observations=true`, `output_mode="full_json_file"`. Note the saved file path.

## Step 2: Extract Node Data

Read the saved trace JSON. For each pipeline node observation (filter to SPAN type with these names), extract:
- **Name**: observation name
- **Status**: level (DEFAULT or ERROR)
- **Duration**: endTime - startTime in seconds
- **Token Usage**: promptTokens + completionTokens (from child GENERATION observations)
- **Cost**: calculatedTotalCost
- **Error**: statusMessage (if ERROR level)

Pipeline nodes to look for (in execution order):
1. HoursPassed
2. LocalScopeDate
3. DateExtractor
4. EarliestPhotoDate
5. MeasurementImages
6. MeasurementImagesValidator
7. PropertyImages (batch tool -- may have multiple child calls)
8. PropertyImagesAggregator
9. RoomNameNormalizer
10. Description
11. Merge
12. HazardValidation
13. RoomsWithId
14. Tasks
15. Equipment
16. Drying
17. Standards
18. Assembly
19. Translation

## Step 3: Extract Key Output Characteristics

For the major LLM nodes, also extract and summarize:

### Description
- Room count, materials count, job_types, water_category, water_class

### Merge
- Room count, materials count, any room merges noted

### RoomsWithId
- Final room count, rooms with floor plan matches, rooms from photos only

### Tasks
- Total task count (project + room), room count with tasks

### Equipment
- Equipment items count, total air movers, total dehumidifiers, AFD count

### Drying
- Chamber count

### Assembly
- Final scope length (character count or line count of output)

## Step 4: Display in Chat

Reply with this format:

```
## Trace Review: <trace_id_first_8>

**Date:** <timestamp> | **Version:** <version> | **Total Latency:** <n>s | **Total Cost:** $<n>
**Status:** <Success/Error> | **Environment:** <production/sdk-experiment>

### Input Summary
- **Property:** <address>
- **Loss Type:** <type> | **Rooms:** <n> | **Photos:** <n> | **Floor Plans:** <n>

### Pipeline Nodes

| # | Node | Status | Duration | Tokens | Cost | Notes |
|---|------|--------|----------|--------|------|-------|
| 1 | HoursPassed | OK | 0.1s | -- | -- | |
| 2 | MeasurementImages | OK | 12.3s | 4500 | $0.02 | 8 rooms extracted |
| 3 | PropertyImages | OK | 15.2s | 12000 | $0.08 | 35 photos, 3 batches |
| 4 | Description | OK | 8.5s | 18000 | $0.12 | 6 rooms, Cat 2, Class 2 |
| 5 | Merge | OK | 6.2s | 15000 | $0.09 | 8 rooms merged |
...

(For ERROR nodes, show the error message in the Notes column)

### Token Breakdown

| Node | Input Tokens | Output Tokens | Total | % of Total |
|------|-------------|---------------|-------|------------|
| Description | <n> | <n> | <n> | <pct>% |
| Merge | <n> | <n> | <n> | <pct>% |
| Tasks | <n> | <n> | <n> | <pct>% |
| PropertyImages | <n> | <n> | <n> | <pct>% |
| Other | <n> | <n> | <n> | <pct>% |
| **Total** | **<n>** | **<n>** | **<n>** | **100%** |

### Cost Breakdown

| Node | Cost | % of Total |
|------|------|------------|
| <node> | $<n> | <pct>% |
...
| **Total** | **$<n>** | **100%** |
```

Sort token and cost breakdowns by value descending. Only include nodes that have non-zero values.
