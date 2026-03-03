"""Data models for the weekly MitScope report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TraceData:
    """Minimal trace data extracted from Langfuse."""

    id: str
    timestamp: datetime
    user_id: str | None
    total_cost: float
    latency: float
    name: str | None = None
    output_is_null: bool = False


@dataclass
class UserStats:
    """Per-user aggregated statistics."""

    email: str
    scopes: int
    avg_cost: float
    total_cost: float
    avg_latency: float = 0.0
    total_latency: float = 0.0


@dataclass
class OrgStats:
    """Per-organization aggregated statistics."""

    name: str
    domain: str
    scopes: int
    employees: int
    avg_cost: float
    total_cost: float
    avg_latency: float = 0.0
    total_latency: float = 0.0


@dataclass
class ActivityEntry:
    """Activity count for a time bucket (day or hour)."""

    label: str
    count: int
    percentage: float


@dataclass
class PercentileStats:
    """Statistical summary with percentiles."""

    average: float
    median: float
    min: float
    max: float
    p75: float
    p95: float
    std_dev: float = 0.0


@dataclass
class ErrorTrace:
    """Details of a single error trace."""

    trace_id: str
    user_id: str | None
    timestamp: datetime
    total_cost: float
    latency: float
    error_type: str
    failing_node: str
    filter_type: str | None = None
    status_message: str = ""
    pipeline_completeness: str = ""


@dataclass
class ErrorTypeGroup:
    """Errors grouped by type and node."""

    error_type: str
    node: str
    count: int
    filter_type: str | None = None
    traces: list[ErrorTrace] = field(default_factory=list)


@dataclass
class AffectedUser:
    """User affected by errors."""

    email: str
    error_count: int
    error_types: str


@dataclass
class UsageReport:
    """Full usage report data (replicates /su)."""

    period_start: datetime
    period_end: datetime
    total_scopes: int
    unique_orgs: int
    unique_users: int
    total_cost: float
    avg_cost: float
    top_users_by_volume: list[UserStats] = field(default_factory=list)
    cost_outliers: list[UserStats] = field(default_factory=list)
    activity_by_day: list[ActivityEntry] = field(default_factory=list)
    activity_by_hour: list[ActivityEntry] = field(default_factory=list)
    peak_day: str = ""
    peak_hours: str = ""
    quiet_hours: str = ""
    orgs: list[OrgStats] = field(default_factory=list)
    users: list[UserStats] = field(default_factory=list)


@dataclass
class CostReport:
    """Full cost & latency report data (replicates /sc)."""

    total_traces: int
    cost_stats: PercentileStats
    latency_stats: PercentileStats
    top_users_by_cost: list[UserStats] = field(default_factory=list)
    top_users_by_latency: list[UserStats] = field(default_factory=list)
    top_orgs_by_cost: list[OrgStats] = field(default_factory=list)
    top_orgs_by_latency: list[OrgStats] = field(default_factory=list)


@dataclass
class ErrorReport:
    """Full error report data (replicates /se)."""

    total_production: int
    total_errors: int
    error_rate: float
    error_groups: list[ErrorTypeGroup] = field(default_factory=list)
    affected_users: list[AffectedUser] = field(default_factory=list)
