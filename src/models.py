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


@dataclass
class TraceEvalReport:
    """Lightweight per-trace evaluation report."""

    trace_id: str
    timestamp: datetime
    user_id: str | None
    latency: float

    # Pipeline health
    pipeline_complete: bool
    nodes_completed: list[str] = field(default_factory=list)
    error_node: str | None = None
    error_type: str | None = None

    # Room stats
    total_rooms: int = 0
    affected_rooms: int = 0
    unaffected_rooms: int = 0
    rooms_from_app: int = 0
    rooms_from_description: int = 0
    rooms_with_measurements: int = 0

    # Input quality stats
    photo_count: int = 0
    floor_plan_count: int = 0
    note_count: int = 0
    has_guidelines: bool = False
    has_moisture: bool = False

    # Data quality flags
    rooms_without_photos: int = 0
    rooms_without_notes: int = 0
    rooms_with_few_photos: int = 0
    floor_plan_discrepancy_sf: float = 0.0
    rooms_may_be_missing: bool = False
    unmatched_floor_plan_rooms: int = 0

    # Version
    version: str = ""

    # Scores
    input_score: int = 0
    input_label: str = ""
    pipeline_score: int = 0
    pipeline_label: str = ""
    issue_score: int = 0
    issue_label: str = ""

    # Flags
    is_initial_scope: bool = False

    # Raw issue data (for bug logging)
    issue_details: dict = field(default_factory=dict)

    # Narrative (Haiku-generated)
    input_assessment: str = ""
    pipeline_assessment: str = ""
    issue_assessment: str = ""
    recommendations: str = ""


# ── Sales Report Models ──────────────────────────────────────────


@dataclass
class SalesTrace:
    """Per-trace data for the Sales page."""

    trace_id: str
    date: str
    version: str
    user_email: str
    time: str
    input_score: str
    pipeline_score: str
    issue_score: str
    overall_score: str
    overall_numeric: float
    rooms: str
    photos: int
    notes: int
    plans: int
    flags: list[str] = field(default_factory=list)
    is_enhanced: bool = False
    bug_summary: str = ""
    narrative_html: str = ""


@dataclass
class SalesUser:
    """Per-user aggregation for the Sales page."""

    email: str
    trace_count: int
    flagged_count: int
    traces: list[SalesTrace] = field(default_factory=list)


@dataclass
class SalesOrg:
    """Per-organization aggregation for the Sales page."""

    name: str
    user_count: int
    trace_count: int
    flagged_count: int
    users: list[SalesUser] = field(default_factory=list)


@dataclass
class SalesReport:
    """Full Sales report data for the 4th tab."""

    period_start: datetime
    period_end: datetime
    total_traces: int
    total_flagged: int
    total_orgs: int
    total_users: int
    orgs: list[SalesOrg] = field(default_factory=list)

    # Flag summary counts
    count_low_score: int = 0
    count_pipeline: int = 0
    count_no_data: int = 0
    count_no_plan: int = 0
    count_fp_mismatch: int = 0
    count_initial_scope: int = 0

