# Scope Usage Report

Generate an ad-hoc production scope usage report using Langfuse trace data.

**Note:** Daily and weekly usage reports are generated automatically by GitHub Actions (`EncircleInc/joe-sandbox`) and synced to `joe/docs/reports/scope-usage.md`. Use this skill only for ad-hoc queries with custom time ranges.

Generate a usage breakdown from production traces with summary stats, organization-level aggregation, and per-user detail. Results are appended to `joe/docs/reports/scope-usage.md` as a new dated entry — existing reports are preserved.

## Usage

`/su` or `/su <time>` where `<time>` is one of:
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

### Step 3: Extract Per-Trace Data

For each trace, extract:
- `userId` (organization/technician email)
- `totalCost` (dollar amount)
- `name` (trace name, to confirm it is a mitigation-scope trace)
- `createdAt` (timestamp)

Filter to only mitigation-scope traces (unnamed traces in the project). Exclude named traces like `experiment-item-run` which belong to other services.

### Step 4: Aggregate

#### 4a: Per-User Aggregation
Group traces by `userId`:
- Per user: total scope count, total cost, average cost per run
- Sort by scope count descending

#### 4b: Organization Aggregation
Derive org name from email domain. Mapping rules:
- `@ca.belfor.com` -> "BELFOR Canada"
- `@encircleapp.com` -> "Encircle (internal)"
- `@firstgeneraledm.ca` -> "First General Edmonton"
- `@firstgeneral.ca` -> "First General"
- `@decconstruction.com` -> "DEC Construction"
- `@rrtfl.com` -> "RRT Florida"
- `@apolloconstructioncorp.com` -> "Apollo Construction"
- `@servicemastertbay.com` -> "ServiceMaster Thunder Bay"
- `@smcalgary.com` -> "ServiceMaster Calgary"
- `@smking.ca` -> "ServiceMaster Kingston"
- `@southeastrestoration.com` -> "Southeast Restoration"
- `@911restoration.com` -> "911 Restoration"
- `@restoration1.com` -> "Restoration 1"
- `@goblusky.com` -> "BluSky Restoration"
- `@capdsus.com` -> "CAPD Sustainable"
- `@zeusrestoration.com` -> "Zeus Restoration"
- `@ungerman.net` -> "Ungerman"
- `@steprises.com` -> "StepRise"
- `@rfconstruction.dki.ca` -> "RF Construction DKI"
- `@advantaclean.com` -> "AdvantaClean"
- `@puroclean.com` -> "PuroClean"
- `@pennroto.com` -> "Penn Roto"
- `@hughescustomperformance.com` -> "Hughes Custom Performance"
- `@quickrestore.com` -> "Quick Restore"
- `@247restoration.com` -> "24/7 Restoration"
- For any unmapped domain: use the domain name portion, title-cased
- Personal email domains (`gmail.com`, `hotmail.com`, `yahoo.com`, `live.com`, `outlook.com`): group each user as their own org using their full email address

Per org: total scopes, unique employees (distinct userIds), average cost per scope, total cost.
Sort by total scopes descending.

#### 4c: Totals and Outliers
- Grand totals: total traces, total cost, overall average cost per scope, unique organizations, unique users
- Cost outliers: any user with avg cost > $2.00/scope (likely large-room-count jobs)
- Top users: top 5 users by scope volume

#### 4d: Activity Patterns
Parse each trace's `createdAt` timestamp to extract day-of-week and hour-of-day (UTC):
- **By Day of Week**: Group traces by day (Mon-Sun). Count scopes per day, calculate % of total.
- **By Hour of Day**: Group traces by hour (0-23 UTC). Count scopes per hour, calculate % of total.
- **Peak & Low**: Identify the single busiest day, the peak 3-hour window (consecutive hours with highest combined count), and the quietest 3-hour window.

### Step 5: Write Report

**APPEND** a new dated entry to `joe/docs/reports/scope-usage.md`. Do NOT overwrite the file.

**5A: Determine section and entry header:**
- Period 7d → `## Weekly Reports (7d)` section → entry header `### Week of {report_date}`
- Period 24h → `## Daily Reports (24h)` section → entry header `### {report_date}`
- Other periods → `## Weekly Reports (7d)` section → entry header `### {report_date} ({period})`

**5B: Check for duplicate.** If the entry header already exists in the file, skip writing and report "already exists" to the user.

**5C: Insert** the new entry immediately after the section header line, before any existing entries in that section. Most-recent-first ordering.

**5D: Update All-Time Summary.** Replace the table under `## All-Time Summary` with the new report's Summary table values.

The entry body must exactly match this structure (use the real computed values):

```markdown
### Week of {report_date}

**Generated:** {YYYY-MM-DD HH:MM UTC} | **Period:** {time_description}

#### Summary

| Metric | Value |
|---|---|
| Total Production Scopes | {N} |
| Unique Organizations | {org_count} |
| Unique Users | {user_count} |
| Total Cost | ${grand_total} |
| Average Cost / Scope | ${overall_avg} |

**Highlights:** Top 3 orgs: {org1} ({scopes} scopes, {employees} employees, ${cost}), {org2} ({scopes} scopes, {employees} employees, ${cost}), {org3} ({scopes} scopes, {employees} employees, ${cost}). {N} cost outliers identified (avg > $2/scope).

#### Top Users by Volume

| User | Scopes | Avg Cost | Total Cost |
|---|---|---|---|
| {email} | {count} | ${avg} | ${total} |
...top 5 users by scope count...

#### Cost Outliers (Avg > $2.00/scope)

| User | Scopes | Avg Cost | Total Cost |
|---|---|---|---|
| {email} | {count} | ${avg} | ${total} |
...all users where avg cost > $2.00, sorted by scope count desc then avg cost desc...

#### Activity Patterns

##### By Day of Week

| Day | Scopes | % |
|---|---|---|
| Mon | {count} | {pct}% |
| Tue | {count} | {pct}% |
| Wed | {count} | {pct}% |
| Thu | {count} | {pct}% |
| Fri | {count} | {pct}% |
| Sat | {count} | {pct}% |
| Sun | {count} | {pct}% |

##### By Hour (UTC)

| Hour | Scopes | % |
|---|---|---|
| 00:00 | {count} | {pct}% |
| 01:00 | {count} | {pct}% |
| 02:00 | {count} | {pct}% |
| ... | ... | ... |
| 23:00 | {count} | {pct}% |

**Peak:** {busiest_day} is the busiest day ({N} scopes, {pct}%). Peak hours: {HH}:00-{HH}:00 UTC ({N} scopes). Quietest: {HH}:00-{HH}:00 UTC ({N} scopes).

#### By Organization

| Organization | Scopes | Employees | Avg Cost | Total Cost |
|---|---|---|---|---|
| {org_name} | {count} | {unique_employees} | ${avg} | ${total} |
...all orgs sorted by scope count desc...
| **TOTAL** | **{N}** | **{unique_users}** | **${overall_avg}** | **${grand_total}** |

#### By User

| User | Scopes | Avg Cost | Total Cost |
|---|---|---|---|
| {email} | {count} | ${avg} | ${total} |
...all users sorted by scope count desc...
| **TOTAL** | **{N}** | **${overall_avg}** | **${grand_total}** |
```

Formatting rules:
- All dollar amounts: `$X.XX` (2 decimal places)
- The h1 title is just "Scope Usage Report"
- Period description examples: "7d", "24h", "3d"
- Organization table sorted by Scopes descending
- User table sorted by Scopes descending
- Cost outlier table sorted by Scopes descending, then Avg Cost descending
- Top users table: exactly 5 rows

### Step 6: Notify User

Print summary in chat:
- Period covered
- Total production scopes
- Unique organizations and unique users
- Total cost and average cost per scope
- Top 3 orgs by volume
- Any cost outliers
- Peak activity: busiest day and peak hours
- Link to scope-usage.md
