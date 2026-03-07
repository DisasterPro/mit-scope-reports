"""Write report data to markdown files with Weekly and Daily sections."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from .models import CostReport, ErrorReport, TraceEvalReport, UsageReport

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


# ── Trace Eval Report ────────────────────────────────────────────

_EVAL_SKELETON = """\
# Scope Trace Evaluations

**Last Updated:** -- | **Total Traces:** 0 | **Avg Input Score:** --/5 | **Avg Pipeline Score:** --/5 | **Avg Overall:** --/5 | **Success Rate:** --%

## Index

| Trace | Date | User | Time | Input | Pipeline | Rooms | Photos | Notes | Plans |
|-------|------|------|------|-------|----------|-------|--------|-------|-------|

---
"""

_EVAL_INDEX_HEADER = "| Trace | Date | User | Time | Input | Pipeline | Rooms | Photos | Notes | Plans |"
_EVAL_INDEX_SEP = "|-------|------|------|------|-------|----------|-------|--------|-------|-------|"


def write_trace_eval_report(
    path: Path, evals: list[TraceEvalReport],
) -> None:
    """Write/update scope-eval-all-runs.md with new trace evaluations."""
    path.parent.mkdir(exist_ok=True)

    if path.exists():
        doc = path.read_text(encoding="utf-8")
    else:
        doc = _EVAL_SKELETON

    # Find existing trace IDs to skip duplicates (full 32-char IDs)
    existing_ids = set(re.findall(r"^## ([a-f0-9]{32}) --", doc, re.MULTILINE))
    # Also match legacy 8-char IDs for backwards compat
    existing_short = set(re.findall(r"^## ([a-f0-9]{8}) --", doc, re.MULTILINE))

    new_evals = [
        e for e in evals
        if e.trace_id not in existing_ids and e.trace_id[:8] not in existing_short
    ]
    if not new_evals:
        logger.info("No new trace evals to write (all already present)")
        return

    # Sort newest first
    new_evals.sort(key=lambda e: e.timestamp, reverse=True)

    # Build new index rows and sections
    new_rows = []
    new_sections = []

    for e in new_evals:
        minutes = int(e.latency // 60)
        seconds = int(e.latency % 60)
        time_str = f"{minutes}m {seconds}s"
        user = e.user_id or "unknown"
        date_str = e.timestamp.strftime("%Y-%m-%d")
        tid = e.trace_id

        row = (
            f"| {tid} | {date_str} | {user} | {time_str} "
            f"| {e.input_score}/5 {e.input_label} "
            f"| {e.pipeline_score}/5 {e.pipeline_label} "
            f"| {e.total_rooms} ({e.affected_rooms}/{e.unaffected_rooms}) "
            f"| {e.photo_count} | {e.note_count} | {e.floor_plan_count} |"
        )
        new_rows.append(row)

        section = _render_trace_eval_section(e, tid, date_str, time_str, user)
        new_sections.append(section)

    # Insert index rows after the separator line
    sep_idx = doc.find(_EVAL_INDEX_SEP)
    if sep_idx != -1:
        insert_pos = sep_idx + len(_EVAL_INDEX_SEP)
        # Find end of line
        nl_pos = doc.find("\n", insert_pos)
        if nl_pos == -1:
            nl_pos = len(doc)
        rows_text = "\n" + "\n".join(new_rows)
        doc = doc[:nl_pos] + rows_text + doc[nl_pos:]

    # Insert sections after the --- separator
    separator_idx = doc.find("\n---\n")
    if separator_idx != -1:
        insert_pos = separator_idx + len("\n---\n")
        sections_text = "\n".join(new_sections) + "\n"
        doc = doc[:insert_pos] + "\n" + sections_text + doc[insert_pos:]

    # Recompute summary stats
    doc = _recompute_eval_stats(doc)

    # Rolling window: remove sections older than 90 days
    doc = _trim_old_eval_sections(doc, days=90)

    path.write_text(doc, encoding="utf-8")
    logger.info("Updated %s with %d new evaluations", path, len(new_evals))


def _render_trace_eval_section(
    e: TraceEvalReport,
    tid: str,
    date_str: str,
    time_str: str,
    user: str,
) -> str:
    """Render a single trace eval section."""
    lines = [
        f"## {tid} -- {date_str}",
        "",
        f"**User:** {user} | **Time:** {time_str}",
        (
            f"**Rooms:** {e.total_rooms} total "
            f"({e.affected_rooms} affected, {e.unaffected_rooms} unaffected) "
            f"| **Photos:** {e.photo_count} | **Notes:** {e.note_count} "
            f"| **Floor Plans:** {e.floor_plan_count}"
        ),
        (
            f"**Input Quality:** {e.input_score}/5 {e.input_label} "
            f"| **Pipeline Health:** {e.pipeline_score}/5 {e.pipeline_label}"
        ),
        "",
    ]

    # What Was Provided table
    room_setup_status = "Good" if e.rooms_from_app > e.total_rooms * 0.5 else (
        "Fair" if e.rooms_from_app > 0 else "Poor"
    )
    photo_status = (
        "None" if e.photo_count == 0 else
        "Minimal" if e.photo_count < 5 else
        "Adequate" if e.photo_count < 15 else "Good"
    )
    note_status = (
        "None" if e.note_count == 0 else
        "Minimal" if e.note_count < e.affected_rooms * 0.5 else
        "Adequate" if e.note_count < e.affected_rooms else "Detailed"
    )
    fp_status = (
        "None" if e.floor_plan_count == 0 else
        "Partial" if e.rooms_with_measurements == 0 else "Complete"
    )
    matching_status = (
        "N/A" if e.floor_plan_count == 0 else
        "Issues" if e.unmatched_floor_plan_rooms > 0 else "Good"
    )

    lines.extend([
        "### What Was Provided",
        "",
        "| Category | Status | Details |",
        "|----------|--------|---------|",
        (
            f"| Room Setup | {room_setup_status} | {e.total_rooms} rooms; "
            f"{e.rooms_from_app} in app, {e.rooms_from_description} from notes |"
        ),
        (
            f"| Field Photos | {photo_status} | {e.photo_count} photos; "
            f"{e.rooms_without_photos} rooms without photos |"
        ),
        (
            f"| Technician Notes | {note_status} | {e.note_count} notes; "
            f"{e.rooms_without_notes} rooms without notes |"
        ),
        (
            f"| Floor Plans | {fp_status} | {e.floor_plan_count} plans; "
            f"{e.rooms_with_measurements} rooms with measurements |"
        ),
        (
            f"| Room Name Matching | {matching_status} | "
            f"{e.unmatched_floor_plan_rooms} unmatched floor plan rooms |"
        ),
        f"| Moisture Data | {'Present' if e.has_moisture else 'None'} | -- |",
        f"| Guidelines | {'Present' if e.has_guidelines else 'None'} | -- |",
        "",
    ])

    # Input Assessment
    lines.extend([
        "### Input Assessment",
        "",
        e.input_assessment or "_No assessment available._",
        "",
    ])

    # Pipeline Assessment
    lines.extend([
        "### Pipeline Assessment",
        "",
        e.pipeline_assessment or "_No assessment available._",
        "",
        "---",
        "",
    ])

    return "\n".join(lines)


def _recompute_eval_stats(doc: str) -> str:
    """Recompute the summary stats line at the top of the eval doc."""
    # Extract all index rows (skip header and separator) -- match both full and short trace IDs
    rows = re.findall(
        r"^\| [a-f0-9]{8,32} \|.*$", doc, re.MULTILINE,
    )

    total = len(rows)
    if total == 0:
        return doc

    input_scores = []
    pipeline_scores = []
    healthy_count = 0

    for row in rows:
        # Extract input score and pipeline score (e.g., "3/5 Adequate | 4/5 Minor")
        input_match = re.search(r"\| (\d)/5 \w+\s*\| (\d)/5 (\w+)", row)
        if input_match:
            input_scores.append(int(input_match.group(1)))
            p_score = int(input_match.group(2))
            pipeline_scores.append(p_score)
            if p_score >= 4:
                healthy_count += 1

    avg_input = sum(input_scores) / len(input_scores) if input_scores else 0
    avg_pipeline = sum(pipeline_scores) / len(pipeline_scores) if pipeline_scores else 0
    avg_overall = (avg_input + avg_pipeline) / 2 if input_scores else 0
    success_rate = (healthy_count / total * 100) if total else 0

    from datetime import datetime, timezone
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    new_stats = (
        f"**Last Updated:** {now_str} | **Total Traces:** {total} "
        f"| **Avg Input Score:** {avg_input:.1f}/5 "
        f"| **Avg Pipeline Score:** {avg_pipeline:.1f}/5 "
        f"| **Avg Overall:** {avg_overall:.1f}/5 "
        f"| **Success Rate:** {success_rate:.0f}%"
    )

    doc = re.sub(
        r"\*\*Last Updated:\*\*.*?\*\*Success Rate:\*\*\s*\S+",
        new_stats,
        doc,
        count=1,
    )

    return doc


def _trim_old_eval_sections(doc: str, days: int = 90) -> str:
    """Remove per-trace sections older than N days (keep index rows)."""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.strftime("%Y-%m-%d")

    # Find all section headers like "## <trace_id> -- 2026-01-01"
    sections = list(re.finditer(
        r"^## [a-f0-9]{8,32} -- (\d{4}-\d{2}-\d{2})\n",
        doc, re.MULTILINE,
    ))

    # Remove sections with dates before cutoff (iterate in reverse)
    for match in reversed(sections):
        date_str = match.group(1)
        if date_str < cutoff_str:
            # Find the end of this section (next ## or end of doc)
            start = match.start()
            next_section = re.search(
                r"^## [a-f0-9]{8} --", doc[match.end():], re.MULTILINE,
            )
            if next_section:
                end = match.end() + next_section.start()
            else:
                end = len(doc)
            doc = doc[:start] + doc[end:]

    return doc
