"""Write report data to markdown files with Weekly and Daily sections."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from .models import CostReport, ErrorReport, UsageReport

logger = logging.getLogger(__name__)

_WEEKLY_HEADER = "## Weekly Reports (7d)"
_DAILY_HEADER = "## Daily Reports (24h)"


def _ensure_doc_structure(path: Path, title: str) -> str:
    """Read existing doc or create skeleton with sections."""
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# {title}\n\n{_WEEKLY_HEADER}\n\n{_DAILY_HEADER}\n\n## Other Reports\n"


def _insert_entry(doc: str, section_header: str, entry: str) -> str:
    """Insert an entry at the top of the given section (after the header line)."""
    idx = doc.find(section_header)
    if idx == -1:
        # Section missing — append it
        doc = doc.rstrip() + f"\n\n{section_header}\n\n{entry}\n"
        return doc

    insert_pos = idx + len(section_header)
    # Skip any trailing whitespace/newlines right after the header
    while insert_pos < len(doc) and doc[insert_pos] in ("\n", "\r"):
        insert_pos += 1

    doc = doc[:idx + len(section_header)] + "\n\n" + entry + "\n\n" + doc[insert_pos:]
    return doc


# ── Usage Report ──────────────────────────────────────────────────

def _render_usage_md(
    usage: UsageReport,
    generated_at: datetime,
    period: str,
) -> str:
    """Render a single usage report entry as markdown."""
    is_weekly = period == "weekly"
    label = "Weekly" if is_weekly else "Daily"
    days = "7d" if is_weekly else "1d"
    period_str = (
        f"{usage.period_start:%Y-%m-%d} to {usage.period_end:%Y-%m-%d}"
    )

    lines = [
        f"### {usage.period_start:%Y-%m-%d} ({label})",
        f"**Generated:** {generated_at:%Y-%m-%d %H:%M} UTC | "
        f"**Period:** {days} ({period_str})",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total Production Scopes | {usage.total_scopes:,} |",
        f"| Unique Organizations | {usage.unique_orgs} |",
        f"| Unique Users | {usage.unique_users} |",
        f"| Total Cost | ${usage.total_cost:.2f} |",
        f"| Average Cost / Scope | ${usage.avg_cost:.2f} |",
        "",
    ]

    # Top users (top 5)
    lines.append("**Top Users:** ")
    top = usage.top_users_by_volume[:5]
    parts = [f"{u.email} ({u.scopes})" for u in top]
    lines[-1] += ", ".join(parts)
    lines.append("")

    # Org summary (top 5)
    lines.append("**Top Orgs:** ")
    top_orgs = usage.orgs[:5]
    parts = [f"{o.name} ({o.scopes})" for o in top_orgs]
    lines[-1] += ", ".join(parts)
    lines.append("")

    if usage.cost_outliers:
        lines.append(
            f"**Cost Outliers:** {len(usage.cost_outliers)} users "
            f"with avg > $1.00/scope"
        )
        lines.append("")

    lines.append("---")
    return "\n".join(lines)


# ── Cost Report ───────────────────────────────────────────────────

def _render_costs_md(
    costs: CostReport,
    usage: UsageReport,
    generated_at: datetime,
    period: str,
) -> str:
    """Render a single cost/latency report entry as markdown."""
    is_weekly = period == "weekly"
    label = "Weekly" if is_weekly else "Daily"
    days = "7d" if is_weekly else "1d"
    period_str = (
        f"{usage.period_start:%Y-%m-%d} to {usage.period_end:%Y-%m-%d}"
    )

    lines = [
        f"### {usage.period_start:%Y-%m-%d} ({label})",
        f"**Generated:** {generated_at:%Y-%m-%d %H:%M} UTC | "
        f"**Period:** {days} ({period_str}) | "
        f"**Traces:** {costs.total_traces:,}",
        "",
        "| Metric | Cost | Latency |",
        "|---|---|---|",
        f"| Average | ${costs.cost_stats.average:.2f} | {costs.latency_stats.average:.1f}s |",
        f"| Median | ${costs.cost_stats.median:.2f} | {costs.latency_stats.median:.1f}s |",
        f"| P75 | ${costs.cost_stats.p75:.2f} | {costs.latency_stats.p75:.1f}s |",
        f"| P95 | ${costs.cost_stats.p95:.2f} | {costs.latency_stats.p95:.1f}s |",
        f"| Min | ${costs.cost_stats.min:.2f} | {costs.latency_stats.min:.1f}s |",
        f"| Max | ${costs.cost_stats.max:.2f} | {costs.latency_stats.max:.1f}s |",
        "",
    ]

    # Top cost users (top 3)
    if costs.top_users_by_cost:
        top = costs.top_users_by_cost[:3]
        parts = [f"{u.email} (${u.avg_cost:.2f})" for u in top]
        lines.append(f"**Top Cost Users:** {', '.join(parts)}")
        lines.append("")

    # Top latency users (top 3)
    if costs.top_users_by_latency:
        top = costs.top_users_by_latency[:3]
        parts = [f"{u.email} ({u.avg_latency:.0f}s)" for u in top]
        lines.append(f"**Top Latency Users:** {', '.join(parts)}")
        lines.append("")

    lines.append("---")
    return "\n".join(lines)


# ── Error Report ──────────────────────────────────────────────────

def _render_errors_md(
    errors: ErrorReport,
    usage: UsageReport,
    generated_at: datetime,
    period: str,
) -> str:
    """Render a single error report entry as markdown."""
    is_weekly = period == "weekly"
    label = "Weekly" if is_weekly else "Daily"
    days = "7d" if is_weekly else "1d"
    period_str = (
        f"{usage.period_start:%Y-%m-%d} to {usage.period_end:%Y-%m-%d}"
    )

    lines = [
        f"### {usage.period_start:%Y-%m-%d} ({label})",
        f"**Generated:** {generated_at:%Y-%m-%d %H:%M} UTC | "
        f"**Period:** {days} ({period_str})",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Total Production Scopes | {errors.total_production:,} |",
        f"| Error Traces | {errors.total_errors} ({errors.error_rate:.1f}%) |",
        "",
    ]

    if errors.error_groups:
        lines.append("| Error Type | Node | Count | Filter |")
        lines.append("|---|---|---|---|")
        for g in errors.error_groups:
            node = g.node or "--"
            filt = g.filter_type or "--"
            lines.append(f"| {g.error_type} | {node} | {g.count} | {filt} |")
        lines.append("")

    if errors.affected_users:
        affected = errors.affected_users[:5]
        parts = [f"{u.email} ({u.error_count}x {u.error_types})" for u in affected]
        lines.append(f"**Affected Users:** {', '.join(parts)}")
        if len(errors.affected_users) > 5:
            lines.append(
                f"  ...and {len(errors.affected_users) - 5} more"
            )
        lines.append("")
    elif errors.total_errors == 0:
        lines.append("No errors detected this period.")
        lines.append("")

    lines.append("---")
    return "\n".join(lines)


# ── Public API ────────────────────────────────────────────────────

def write_markdown_reports(
    docs_dir: Path,
    usage: UsageReport,
    costs: CostReport,
    errors: ErrorReport,
    generated_at: datetime,
    period: str,
) -> None:
    """Write/update the three markdown report files."""
    docs_dir.mkdir(exist_ok=True)
    section = _WEEKLY_HEADER if period == "weekly" else _DAILY_HEADER

    # scope-usage.md
    usage_path = docs_dir / "scope-usage.md"
    doc = _ensure_doc_structure(usage_path, "Scope Usage Report")
    entry = _render_usage_md(usage, generated_at, period)
    doc = _insert_entry(doc, section, entry)
    usage_path.write_text(doc, encoding="utf-8")
    logger.info("Updated %s", usage_path)

    # scope-costs.md
    costs_path = docs_dir / "scope-costs.md"
    doc = _ensure_doc_structure(costs_path, "Scope Cost & Latency Report")
    entry = _render_costs_md(costs, usage, generated_at, period)
    doc = _insert_entry(doc, section, entry)
    costs_path.write_text(doc, encoding="utf-8")
    logger.info("Updated %s", costs_path)

    # scope-errors.md
    errors_path = docs_dir / "scope-errors.md"
    doc = _ensure_doc_structure(errors_path, "Scope Error Report")
    entry = _render_errors_md(errors, usage, generated_at, period)
    doc = _insert_entry(doc, section, entry)
    errors_path.write_text(doc, encoding="utf-8")
    logger.info("Updated %s", errors_path)
