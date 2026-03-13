# Scope Cost & Latency Report

Generate an ad-hoc production scope cost and latency analytics report using Langfuse trace data.

**Note:** Daily and weekly cost reports are generated automatically by GitHub Actions (`EncircleInc/joe-sandbox`) and synced to `joe/docs/reports/scope-costs.md`. Use this skill only for ad-hoc queries with custom time ranges.

Generate cost and latency analytics from production traces. Shows aggregate metrics, top 10 users and organizations by cost and latency. Results are appended to `joe/docs/reports/scope-costs.md` as a new dated entry — existing reports are preserved.

## Usage

`/sc` or `/sc <time>` where `<time>` is one of:
- Time shorthand: `24h`, `3d`, `7d`
- Raw minutes: `1440`
- A Langfuse URL (date range parsed from query params)

Arguments: `$ARGUMENTS`

Max lookback: 7 days (10080 minutes, Langfuse MCP limit).

## Process

### Step 1: Parse Time Input

Extract time range from `$ARGUMENTS`:
- If shorthand (e.g., `24h`, `3d`, `7d`): convert to minutes (24h=1440, 3d=4320, 7d=10080)
- If raw number: use as minutes directly
- If Langfuse URL: parse date params from query string, calculate minutes from now to the start date. Cap at 10080.
- Default if no argument: `7d` (10080 minutes)

Calculate `start_date` and `end_date` for report header.

### Step 2: Fetch All Traces

Use Langfuse MCP to paginate through all traces in the time window:

```
page = 1
all_traces = []
loop:
  result = fetch_traces(age=N, limit=100, page=page, output_mode="full_json_string")
  all_traces += result.data
  if len(result.data) < 100: break
  page += 1
```

### Step 3: Extract Per-Trace Metrics

For each trace, extract:
- `totalCost` (dollar amount)
- `latency` (seconds, from trace `latency` field)
- `userId` (org/user email)
- `createdAt` (timestamp)
- `name` (trace name)
- `environment` (must be `production`)

Filter to only production mitigation-scope traces (unnamed traces with `environment=production`). Exclude named traces like `experiment-item-run`.

### Step 4: Calculate Statistics

#### 4a: Aggregate Metrics
**Cost metrics:**
- Average cost
- Median cost
- Min / Max cost
- P75, P95 cost
- Standard deviation

**Latency metrics:**
- Average latency (seconds)
- Median latency
- P75, P95 latency
- Min / Max latency

#### 4b: Per-User Aggregation
Group traces by `userId`:
- Per user: scope count, avg cost, total cost, avg latency

#### 4c: Organization Aggregation
Derive org name from email domain using the same mapping as `/su`:
- `@ca.belfor.com` -> "BELFOR Canada"
- `@encircleapp.com` -> "Encircle (internal)"
- `@rrtfl.com` -> "RRT Florida"
- `@apolloconstructioncorp.com` -> "Apollo Construction"
- `@decconstruction.com` -> "DEC Construction"
- `@911restoration.com` -> "911 Restoration"
- `@advantaclean.com` -> "AdvantaClean"
- `@southeastrestoration.com` -> "Southeast Restoration"
- `@firstgeneral.ca` -> "First General"
- `@firstgeneraledm.ca` -> "First General Edmonton"
- `@goblusky.com` -> "BluSky Restoration"
- `@puroclean.com` -> "PuroClean"
- `@restoration1.com` -> "Restoration 1"
- `@servicemastertbay.com` -> "ServiceMaster Thunder Bay"
- `@smcalgary.com` -> "ServiceMaster Calgary"
- `@smking.ca` -> "ServiceMaster Kingston"
- `@capdsus.com` -> "CAPD Sustainable"
- `@zeusrestoration.com` -> "Zeus Restoration"
- `@ungerman.net` -> "Ungerman"
- `@steprises.com` -> "StepRise"
- `@rfconstruction.dki.ca` -> "RF Construction DKI"
- `@pennroto.com` -> "Penn Roto"
- `@hughescustomperformance.com` -> "Hughes Custom Performance"
- `@quickrestore.com` -> "Quick Restore"
- `@247restoration.com` -> "24/7 Restoration"
- For any unmapped domain: use the domain name portion, title-cased
- Personal email domains (`gmail.com`, `hotmail.com`, `yahoo.com`, `live.com`, `outlook.com`): use full email as org name

Per org: scope count, avg cost, total cost, avg latency.

### Step 5: Write Report

**APPEND** a new dated entry to `joe/docs/reports/scope-costs.md`. Do NOT overwrite the file.

**5A: Determine section and entry header:**
- Period 7d → `## Weekly Reports (7d)` section → entry header `### Week of {report_date}`
- Period 24h → `## Daily Reports (24h)` section → entry header `### {report_date}`
- Other periods → `## Weekly Reports (7d)` section → entry header `### {report_date} ({period})`

**5B: Check for duplicate.** If the entry header already exists in the file, skip writing and report "already exists" to the user.

**5C: Insert** the new entry immediately after the section header line, before any existing entries. Most-recent-first ordering.

**5D: Update All-Time Summary.** Replace the table under `## All-Time Summary` with the new report's Cost Summary table values.

The entry body must exactly match this structure (use the real computed values):

```markdown
### Week of {report_date}

**Generated:** {YYYY-MM-DD HH:MM UTC} | **Period:** {time_description} | **Traces:** {N}

#### Cost Summary

| Metric | Value |
|---|---|
| Average | ${avg} |
| Median | ${median} |
| Min / Max | ${min} / ${max} |
| P75 | ${p75} |
| P95 | ${p95} |
| Std Dev | ${stdev} |

#### Latency Summary

| Metric | Value |
|---|---|
| Average | {avg}s |
| Median | {median}s |
| P75 | {p75}s |
| P95 | {p95}s |
| Min / Max | {min}s / {max}s |

#### Top 10 Users by Avg Cost

| User | Scopes | Avg Cost | Total Cost |
|---|---|---|---|
| {email} | {count} | ${avg} | ${total} |
...top 10 users by avg cost desc...

#### Top 10 Users by Avg Latency

| User | Scopes | Avg Latency |
|---|---|---|
| {email} | {count} | {avg}s |
...top 10 users by avg latency desc...

#### Top 10 Organizations by Avg Cost

| Organization | Scopes | Avg Cost | Total Cost |
|---|---|---|---|
| {org_name} | {count} | ${avg} | ${total} |
...top 10 orgs by avg cost desc...

#### Top 10 Organizations by Avg Latency

| Organization | Scopes | Avg Latency |
|---|---|---|
| {org_name} | {count} | {avg}s |
...top 10 orgs by avg latency desc...
```

Formatting rules:
- All dollar amounts: `$X.XX` (2 decimal places)
- All latencies: `X.Xs` (1 decimal place, in seconds)
- User tables sorted by the relevant metric descending
- Org tables sorted by the relevant metric descending
- Exactly 10 rows per table (or all rows if fewer than 10 exist)

### Step 6: Notify User

Print summary in chat:
- Period covered
- Traces analyzed
- Average cost and average latency (headline numbers)
- Top cost outlier user and org
- Link to scope-costs.md
