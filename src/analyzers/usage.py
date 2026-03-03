"""Usage analytics -- replicates the /su skill."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from ..models import (
    ActivityEntry,
    OrgStats,
    TraceData,
    UsageReport,
    UserStats,
)
from ..org_resolver import resolve_org

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def analyze_usage(
    traces: list[TraceData],
    period_start: datetime,
    period_end: datetime,
) -> UsageReport:
    """Compute all usage analytics from production traces."""
    total_scopes = len(traces)
    total_cost = sum(t.total_cost for t in traces)
    avg_cost = total_cost / total_scopes if total_scopes else 0.0

    # Group by user
    user_data: dict[str, list[TraceData]] = defaultdict(list)
    for t in traces:
        key = t.user_id or "unknown"
        user_data[key].append(t)

    unique_users = len(user_data)

    # Build user stats
    all_user_stats: list[UserStats] = []
    for email, user_traces in user_data.items():
        count = len(user_traces)
        total = sum(t.total_cost for t in user_traces)
        avg = total / count if count else 0.0
        total_lat = sum(t.latency for t in user_traces)
        avg_lat = total_lat / count if count else 0.0
        all_user_stats.append(
            UserStats(
                email=email,
                scopes=count,
                avg_cost=avg,
                total_cost=total,
                avg_latency=avg_lat,
                total_latency=total_lat,
            )
        )

    # Sort by scope count descending
    all_user_stats.sort(key=lambda u: u.scopes, reverse=True)

    # Top 5 users by volume
    top_users = all_user_stats[:5]

    # Cost outliers (avg > $1.00)
    cost_outliers = sorted(
        [u for u in all_user_stats if u.avg_cost > 1.0],
        key=lambda u: u.avg_cost,
        reverse=True,
    )

    # Organization stats
    org_users: dict[str, dict[str, list[TraceData]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for email, user_traces in user_data.items():
        org_name = resolve_org(email)
        org_users[org_name][email] = user_traces

    org_stats: list[OrgStats] = []
    for org_name, users_map in org_users.items():
        all_org_traces = [t for traces_list in users_map.values() for t in traces_list]
        count = len(all_org_traces)
        total = sum(t.total_cost for t in all_org_traces)
        avg = total / count if count else 0.0
        total_lat = sum(t.latency for t in all_org_traces)
        avg_lat = total_lat / count if count else 0.0
        domain = ""
        for email in users_map:
            if "@" in email:
                domain = email.split("@")[1]
                break
        org_stats.append(
            OrgStats(
                name=org_name,
                domain=domain,
                scopes=count,
                employees=len(users_map),
                avg_cost=avg,
                total_cost=total,
                avg_latency=avg_lat,
                total_latency=total_lat,
            )
        )

    org_stats.sort(key=lambda o: o.scopes, reverse=True)
    unique_orgs = len(org_stats)

    # Activity by day of week
    day_counts: dict[int, int] = defaultdict(int)
    for t in traces:
        day_counts[t.timestamp.weekday()] += 1

    activity_by_day: list[ActivityEntry] = []
    for i, name in enumerate(DAY_NAMES):
        count = day_counts.get(i, 0)
        pct = (count / total_scopes * 100) if total_scopes else 0.0
        activity_by_day.append(ActivityEntry(label=name, count=count, percentage=pct))

    # Peak day
    peak_day_entry = max(activity_by_day, key=lambda a: a.count) if activity_by_day else None
    peak_day = (
        f"{peak_day_entry.label} ({peak_day_entry.count} scopes, {peak_day_entry.percentage:.1f}%)"
        if peak_day_entry
        else ""
    )

    # Activity by hour (UTC)
    hour_counts: dict[int, int] = defaultdict(int)
    for t in traces:
        hour_counts[t.timestamp.hour] += 1

    activity_by_hour: list[ActivityEntry] = []
    for h in range(24):
        count = hour_counts.get(h, 0)
        pct = (count / total_scopes * 100) if total_scopes else 0.0
        activity_by_hour.append(
            ActivityEntry(label=f"{h:02d}:00", count=count, percentage=pct)
        )

    # Peak hours (find the 3-hour window with most scopes)
    if total_scopes:
        best_start = 0
        best_count = 0
        for start in range(24):
            window_count = sum(
                hour_counts.get((start + offset) % 24, 0) for offset in range(3)
            )
            if window_count > best_count:
                best_count = window_count
                best_start = start
        end_hour = (best_start + 3) % 24
        peak_hours = f"{best_start:02d}:00-{end_hour:02d}:00 UTC ({best_count} scopes)"

        # Quietest 3-hour window
        worst_start = 0
        worst_count = total_scopes
        for start in range(24):
            window_count = sum(
                hour_counts.get((start + offset) % 24, 0) for offset in range(3)
            )
            if window_count < worst_count:
                worst_count = window_count
                worst_start = start
        quiet_end = (worst_start + 3) % 24
        quiet_hours = f"{worst_start:02d}:00-{quiet_end:02d}:00 UTC ({worst_count} scopes)"
    else:
        peak_hours = ""
        quiet_hours = ""

    return UsageReport(
        period_start=period_start,
        period_end=period_end,
        total_scopes=total_scopes,
        unique_orgs=unique_orgs,
        unique_users=unique_users,
        total_cost=total_cost,
        avg_cost=avg_cost,
        top_users_by_volume=top_users,
        cost_outliers=cost_outliers,
        activity_by_day=activity_by_day,
        activity_by_hour=activity_by_hour,
        peak_day=peak_day,
        peak_hours=peak_hours,
        quiet_hours=quiet_hours,
        orgs=org_stats,
        users=all_user_stats,
    )
