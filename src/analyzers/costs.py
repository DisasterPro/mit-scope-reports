"""Cost & latency analytics -- replicates the /sc skill."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict

from ..models import (
    CostReport,
    OrgStats,
    PercentileStats,
    TraceData,
    UserStats,
)
from ..org_resolver import resolve_org


def _percentile(sorted_data: list[float], p: float) -> float:
    """Calculate the p-th percentile from sorted data."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    k = (n - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def _compute_stats(values: list[float]) -> PercentileStats:
    """Compute full percentile stats for a list of values."""
    if not values:
        return PercentileStats(
            average=0.0, median=0.0, min=0.0, max=0.0, p75=0.0, p95=0.0, std_dev=0.0
        )

    sorted_vals = sorted(values)
    avg = sum(sorted_vals) / len(sorted_vals)
    med = statistics.median(sorted_vals)
    std = statistics.stdev(sorted_vals) if len(sorted_vals) > 1 else 0.0

    return PercentileStats(
        average=avg,
        median=med,
        min=sorted_vals[0],
        max=sorted_vals[-1],
        p75=_percentile(sorted_vals, 75),
        p95=_percentile(sorted_vals, 95),
        std_dev=std,
    )


def analyze_costs(traces: list[TraceData]) -> CostReport:
    """Compute all cost & latency analytics from production traces."""
    costs = [t.total_cost for t in traces]
    latencies = [t.latency for t in traces]

    cost_stats = _compute_stats(costs)
    latency_stats = _compute_stats(latencies)

    # Group by user
    user_data: dict[str, list[TraceData]] = defaultdict(list)
    for t in traces:
        key = t.user_id or "unknown"
        user_data[key].append(t)

    # Build user stats for cost ranking
    user_stats_cost: list[UserStats] = []
    user_stats_latency: list[UserStats] = []
    for email, user_traces in user_data.items():
        count = len(user_traces)
        total_cost = sum(t.total_cost for t in user_traces)
        avg_cost = total_cost / count if count else 0.0
        total_lat = sum(t.latency for t in user_traces)
        avg_lat = total_lat / count if count else 0.0

        user_stats_cost.append(
            UserStats(
                email=email,
                scopes=count,
                avg_cost=avg_cost,
                total_cost=total_cost,
                avg_latency=avg_lat,
            )
        )
        user_stats_latency.append(
            UserStats(
                email=email,
                scopes=count,
                avg_cost=avg_cost,
                total_cost=total_cost,
                avg_latency=avg_lat,
            )
        )

    # Top 10 by avg cost and avg latency
    user_stats_cost.sort(key=lambda u: u.avg_cost, reverse=True)
    user_stats_latency.sort(key=lambda u: u.avg_latency, reverse=True)

    # Organization stats
    org_data: dict[str, list[TraceData]] = defaultdict(list)
    org_users_map: dict[str, set[str]] = defaultdict(set)
    for t in traces:
        email = t.user_id or "unknown"
        org_name = resolve_org(email)
        org_data[org_name].append(t)
        org_users_map[org_name].add(email)

    org_stats_cost: list[OrgStats] = []
    org_stats_latency: list[OrgStats] = []
    for org_name, org_traces in org_data.items():
        count = len(org_traces)
        total_cost = sum(t.total_cost for t in org_traces)
        avg_cost = total_cost / count if count else 0.0
        total_lat = sum(t.latency for t in org_traces)
        avg_lat = total_lat / count if count else 0.0
        employees = len(org_users_map[org_name])

        entry = OrgStats(
            name=org_name,
            domain="",
            scopes=count,
            employees=employees,
            avg_cost=avg_cost,
            total_cost=total_cost,
            avg_latency=avg_lat,
        )
        org_stats_cost.append(entry)
        org_stats_latency.append(
            OrgStats(
                name=org_name,
                domain="",
                scopes=count,
                employees=employees,
                avg_cost=avg_cost,
                total_cost=total_cost,
                avg_latency=avg_lat,
            )
        )

    org_stats_cost.sort(key=lambda o: o.avg_cost, reverse=True)
    org_stats_latency.sort(key=lambda o: o.avg_latency, reverse=True)

    return CostReport(
        total_traces=len(traces),
        cost_stats=cost_stats,
        latency_stats=latency_stats,
        top_users_by_cost=user_stats_cost[:10],
        top_users_by_latency=user_stats_latency[:10],
        top_orgs_by_cost=org_stats_cost[:10],
        top_orgs_by_latency=org_stats_latency[:10],
    )
