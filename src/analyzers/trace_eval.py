"""Per-trace lightweight evaluation -- hybrid Python stats + LLM narrative."""

from __future__ import annotations

import json
import logging
import os
import re
import time

from ..langfuse_client import LangfuseDataFetcher
from ..models import TraceData, TraceEvalReport

logger = logging.getLogger(__name__)

EXPECTED_NODES = [
    "Description", "PropertyImages", "MeasurementImages",
    "PropertyImagesAggregator", "MeasurementImagesValidator",
    "RoomNameNormalizer", "Merge", "RoomsWithId", "Tasks",
    "Equipment", "Standards", "Drying", "Assembly", "Translation",
]

_INPUT_LABELS = {1: "Poor", 2: "Minimal", 3: "Adequate", 4: "Good", 5: "Excellent"}
_PIPELINE_LABELS = {
    1: "Failed", 2: "Significant", 3: "Moderate", 4: "Minor", 5: "Healthy",
}
_ISSUE_LABELS = {
    1: "Critical", 2: "Significant", 3: "Moderate", 4: "Minor", 5: "Clean",
}

HAIKU_PROMPT = """\
You are writing a brief evaluation of a water damage scope generated for
a field technician. This may be sent directly to the user. Use plain
language, no technical jargon, no internal system names.

## Stats
{stats_json}

## Photo Analysis
Photos submitted: {photo_count}
Per-photo details (room assignments, damage relevance, temporal class):
{photo_agg_data}

Photo coverage gaps:
- Affected rooms without photos: {rooms_without_photos}
- Rooms with few photos: {rooms_with_few_photos}
- Unaffected rooms showing photo damage: {photo_damage_discrepancies}

## Note Content
Notes found: {note_count}
Note snippets (first 300 chars each):
{note_snippets}

Note quality issues:
- Rooms without notes: {rooms_without_notes_detail}
- Rooms with insufficient notes: {insufficient_notes_detail}

## Room Setup
Room sources: {room_source_breakdown}
Organizational room findings: {org_room_findings}
Room names and affected status: {room_names_list}

## Floor Plans & Measurements
Floor plans: {floor_plan_count}
Rooms matched by name: {matched_by_name}
Rooms matched by ID: {matched_by_id}
Unmatched floor plan rooms: {unmatched_fp_rooms}
Rooms with missing measurements: {missing_measurements}
Area discrepancy: {discrepancy_sf} SF ({discrepancy_pct}%)

## Room Name Matching
Room matching details: {room_matching_details}
Floor plan rooms that could not match any claim room: {unmatched_fp_rooms}
Claim rooms that could not match any floor plan room: {unmatched_claim_rooms}

## Pipeline Data Quality Notes (from scope output)
{data_quality_notes_section}

## Structured Data Quality Issues
{issue_data_section}

## Domain Rules (follow strictly)
- Moisture readings help MONITOR drying progress over multiple visits.
  Equipment (air movers, dehumidifiers) is sized from room measurements
  and IICRC S500 standards, not moisture data.
- Floor plan measurements enable task quantity calculations (SF, LF).
  Without them, quantities show "TBD" and must be filled in manually.
- Rooms created in the app sync back to the field application.
  Rooms inferred from notes only do not sync back.
- Floor plan room names MUST match claim room names for measurements to
  be assigned. If "Bedroom 1" is on the floor plan but "Master Bedroom"
  is in the claim, the system cannot match them. Always recommend users
  check that their floor plan labels match their claim room names BEFORE
  running the scope.
- Do NOT mention cost, pricing, or dollar amounts anywhere.
- Do NOT use internal names like "PropertyImages", "RoomsWithId",
  "Assembly", "Merge". Say "photos", "room data", "scope", "system".

Write exactly four sections in markdown:

### Input Assessment
1-2 paragraphs covering:
- What was provided and how well organized (photos labeled to right rooms?
  notes detailed or generic? rooms set up in app or inferred?)
- Specific gaps found (rooms without photos, rooms without notes, etc.)
- Room name matching issues if any (floor plan names vs claim names)

### Pipeline Assessment
1 paragraph covering:
- Processing time and whether it completed successfully
- Any data quality issues the system detected (missing measurements,
  photo-damage mismatches, organizational rooms, etc.)
- Do NOT mention cost

### Issue Assessment
1-2 paragraphs covering:
- Summarize each data quality issue found (standard violations, material
  conflicts, scope conflicts, equipment sizing issues, missing measurements)
- Group by type and describe in plain language
- If no issues found, say "No data quality issues were detected."

### Recommendations
Numbered list of 3-5 actionable steps:
- Specific to THIS scope's gaps (not generic advice)
- Written for a field technician, plain language
- Explain WHY each step matters
- Focus on what can be improved for this and future scopes
- Do NOT mention cost, pricing, or internal system names
"""


def analyze_trace_evals(
    traces: list[TraceData],
    fetcher: LangfuseDataFetcher,
    llm_client=None,
) -> list[TraceEvalReport]:
    """Run lightweight eval on each trace. Returns list of TraceEvalReport."""
    reports: list[TraceEvalReport] = []

    for t in traces:
        try:
            report = _evaluate_single_trace(t, fetcher, llm_client)
            reports.append(report)
        except Exception:
            logger.exception("Failed to evaluate trace %s", t.id)

    logger.info("Evaluated %d of %d traces", len(reports), len(traces))
    return reports


def _evaluate_single_trace(
    trace_data: TraceData,
    fetcher: LangfuseDataFetcher,
    llm_client=None,
) -> TraceEvalReport:
    """Evaluate a single trace: extract stats, score, generate narrative."""
    full = fetcher.fetch_trace_full(trace_data.id)
    trace = full["trace"]
    observations = full["observations"]

    # --- Extract version ---
    version = _extract_version(trace)

    # --- Extract stats ---
    input_stats = _extract_input_stats(trace)
    room_stats = _extract_room_stats(observations)
    pipeline_health = _extract_pipeline_health(observations)
    qualitative = _extract_qualitative_data(trace, observations)

    # --- Extract issue data ---
    issue_data = _extract_issue_data(observations)

    # --- Score ---
    input_score, input_label, is_initial_scope = _score_input(input_stats, room_stats)
    pipeline_score, pipeline_label = _score_pipeline(
        trace_data, pipeline_health, room_stats,
    )
    issue_score, issue_label = _score_issues(issue_data)

    report = TraceEvalReport(
        trace_id=trace_data.id,
        timestamp=trace_data.timestamp,
        version=version,
        user_id=trace_data.user_id,
        latency=trace_data.latency,
        pipeline_complete=pipeline_health["complete"],
        nodes_completed=pipeline_health["completed_nodes"],
        error_node=pipeline_health.get("error_node"),
        error_type=pipeline_health.get("error_type"),
        total_rooms=room_stats.get("total", 0),
        affected_rooms=room_stats.get("affected", 0),
        unaffected_rooms=room_stats.get("unaffected", 0),
        rooms_from_app=room_stats.get("from_app", 0),
        rooms_from_description=room_stats.get("from_description", 0),
        rooms_with_measurements=room_stats.get("with_measurements", 0),
        photo_count=input_stats.get("photo_count", 0),
        floor_plan_count=input_stats.get("floor_plan_count", 0),
        note_count=input_stats.get("note_count", 0),
        has_guidelines=input_stats.get("has_guidelines", False),
        has_moisture=input_stats.get("has_moisture", False),
        thermal_count=input_stats.get("thermal_count", 0),
        pano_count=input_stats.get("pano_count", 0),
        video_count=input_stats.get("video_count", 0),
        has_general_notes=input_stats.get("has_general_notes", False),
        total_structures=input_stats.get("total_structures", 0),
        structural_count=input_stats.get("structural_count", 0),
        org_count=input_stats.get("org_count", 0),
        org_names=input_stats.get("org_names", []),
        rooms_without_photos=room_stats.get("rooms_without_photos", 0),
        rooms_without_notes=room_stats.get("rooms_without_notes", 0),
        rooms_with_few_photos=room_stats.get("rooms_with_few_photos", 0),
        floor_plan_discrepancy_sf=room_stats.get("discrepancy_sf", 0.0),
        rooms_may_be_missing=room_stats.get("rooms_may_be_missing", False),
        unmatched_floor_plan_rooms=room_stats.get("unmatched_fp_rooms", 0),
        rooms_with_missing_measurements=room_stats.get("rooms_with_missing_measurements", 0),
        input_score=input_score,
        input_label=input_label,
        is_initial_scope=is_initial_scope,
        pipeline_score=pipeline_score,
        pipeline_label=pipeline_label,
        issue_score=issue_score,
        issue_label=issue_label,
        issue_details=issue_data,
    )

    # --- Generate narrative via LLM ---
    if llm_client:
        try:
            narrative = _generate_narrative(
                report, input_stats, room_stats, qualitative, llm_client,
                issue_data=issue_data,
            )
            report.input_assessment = narrative.get("input_assessment", "")
            report.pipeline_assessment = narrative.get("pipeline_assessment", "")
            report.issue_assessment = narrative.get("issue_assessment", "")
            report.recommendations = narrative.get("recommendations", "")
        except Exception:
            logger.exception("LLM narrative generation failed for %s", trace_data.id)
            report.input_assessment = _fallback_input_summary(report)
            report.pipeline_assessment = _fallback_pipeline_summary(report)
            report.issue_assessment = _fallback_issue_summary(issue_data)
            report.recommendations = _fallback_recommendations(report, issue_data)
    else:
        report.input_assessment = _fallback_input_summary(report)
        report.pipeline_assessment = _fallback_pipeline_summary(report)
        report.issue_assessment = _fallback_issue_summary(issue_data)
        report.recommendations = _fallback_recommendations(report, issue_data)

    return report


# ── Extraction ────────────────────────────────────────────────────


def _extract_version(trace) -> str:
    """Extract pipeline version from trace metadata."""
    if not trace:
        return "unknown"

    # Try trace.version first (e.g. "V29.2")
    if hasattr(trace, "version") and trace.version:
        return str(trace.version)

    # Try trace.release (git hash) -- return short hash
    if hasattr(trace, "release") and trace.release:
        return str(trace.release)[:8]

    # Try metadata dict
    if hasattr(trace, "metadata") and isinstance(trace.metadata, dict):
        v = trace.metadata.get("version") or trace.metadata.get("pipeline_version")
        if v:
            return str(v)

    return "unknown"


def _extract_input_stats(trace) -> dict:
    """Extract input stats from trace.input."""
    if not trace or not trace.input:
        return {}

    inp = trace.input if isinstance(trace.input, dict) else {}
    description = inp.get("description", "") or ""

    # Scan property images for thermal/360
    prop_images = inp.get("property_images", []) or []
    thermal_count = 0
    pano_count = 0
    for img in prop_images:
        fname = ""
        if isinstance(img, dict):
            fname = str(img.get("filename", "")) + str(img.get("context", ""))
        elif isinstance(img, str):
            fname = img
        fname_lower = fname.lower()
        if any(kw in fname_lower for kw in ("thermal", "flir", "infrared", "ir_")):
            thermal_count += 1
        if any(kw in fname_lower for kw in ("360", "pano", "panoramic", "equirectangular")):
            pano_count += 1

    # Parse structures from input description headers (not from Merge rooms,
    # which only contains structures that have surviving rooms)
    _ORG_PATTERNS = [
        "initial visit", "cause of loss", "data", "checklist", "documentation",
        "admin", "photo", "video", "phase", "contents", "content", "pack out",
        "inspection", "pre existing", "sketch", "scope", "emergency", "repair",
        "moisture reading",
    ]
    struct_names = re.findall(r"## Structure: (.+)", description)
    structural_count = 0
    org_count = 0
    org_names_list = []
    for sname in struct_names:
        name_lower = sname.lower().strip()
        if any(pat in name_lower for pat in _ORG_PATTERNS):
            org_count += 1
            org_names_list.append(sname.strip())
        else:
            structural_count += 1

    return {
        "photo_count": len(prop_images),
        "floor_plan_count": len(inp.get("measurement_images", []) or []),
        "note_count": description.count("<NOTE>"),
        "video_count": description.count("<ROOM_VIDEO>"),
        "has_guidelines": bool(inp.get("guidelines")),
        "has_moisture": "moisture_monitoring" in description.lower()
            or "drying chamber" in description.lower(),
        "has_general_notes": "## General Notes" in description,
        "thermal_count": thermal_count,
        "pano_count": pano_count,
        "total_structures": len(struct_names),
        "structural_count": structural_count,
        "org_count": org_count,
        "org_names": org_names_list,
        "description_snippet": description[:500],
        "note_snippets": _extract_note_snippets(description),
    }


def _extract_note_snippets(description: str) -> list[str]:
    """Extract first 300 chars of each <NOTE> block."""
    snippets = []
    for match in re.finditer(r"<NOTE>(.*?)</NOTE>", description, re.DOTALL):
        content = match.group(1).strip()
        snippets.append(content[:300])
    return snippets


def _extract_room_stats(observations: dict) -> dict:
    """Extract room stats from RoomsWithId observation output."""
    rwi = observations.get("RoomsWithId")
    if not rwi or not rwi.output:
        return {}

    output = rwi.output if isinstance(rwi.output, dict) else {}
    rooms = output.get("rooms", [])
    metrics = output.get("metrics", {})
    photo_cov = output.get("photo_coverage", {})
    note_qual = output.get("note_quality", {})
    fp_disc = output.get("floor_plan_discrepancy", {})
    validation = output.get("validation", {})

    from_app = sum(1 for r in rooms if r.get("app_room_id") is not None)
    from_desc = sum(
        1 for r in rooms
        if (r.get("room_source") or {}).get("source") == "description"
    )
    with_meas = sum(1 for r in rooms if (r.get("measurements") or {}).get("measurements_available", False))

    room_names = [
        {
            "room_name": r.get("room_name", "?"),
            "floor_name": r.get("floor_name", "?"),
            "affected": r.get("affected", False),
        }
        for r in rooms
    ]

    # Merge data quality for room matching
    merge_obs = observations.get("Merge")
    merge_dq = {}
    if merge_obs and merge_obs.output and isinstance(merge_obs.output, dict):
        merge_dq = merge_obs.output.get("data_quality", {})

    return {
        "total": metrics.get("total_room_count", len(rooms)),
        "affected": metrics.get("affected_room_count", 0),
        "unaffected": metrics.get("unaffected_room_count", 0),
        "from_app": from_app,
        "from_description": from_desc,
        "with_measurements": with_meas,
        "rooms_without_photos": len(photo_cov.get("rooms_without_photos", [])),
        "rooms_with_few_photos": len(photo_cov.get("rooms_with_few_photos", [])),
        "photo_damage_in_unaffected": photo_cov.get(
            "photo_damage_in_unaffected_rooms", []
        ),
        "rooms_without_notes": len(note_qual.get("rooms_without_notes", [])),
        "rooms_without_notes_detail": note_qual.get("rooms_without_notes", []),
        "rooms_with_insufficient_notes": note_qual.get(
            "rooms_with_insufficient_notes", []
        ),
        "discrepancy_sf": fp_disc.get("discrepancy_sf", 0.0),
        "discrepancy_pct": fp_disc.get("discrepancy_pct", 0.0),
        "rooms_may_be_missing": fp_disc.get("rooms_may_be_missing", False),
        "validation": validation,
        "room_names": room_names,
        "matched_by_name": merge_dq.get("rooms_matched_by_name", []),
        "matched_by_id": merge_dq.get("rooms_matched_by_id", []),
        "unmatched_fp_rooms": len(merge_dq.get("unmatched_floor_plan_rooms", [])),
        "unmatched_fp_rooms_list": merge_dq.get("unmatched_floor_plan_rooms", []),
        "missing_measurements_list": merge_dq.get(
            "rooms_with_missing_measurements", []
        ),
        "affected_rooms_without_photos_list": merge_dq.get(
            "affected_rooms_without_photos", []
        ),
        "material_conflicts": merge_dq.get("material_conflicts", []),
        "org_room_findings": [],
        "rooms_with_missing_measurements": len(merge_dq.get("rooms_with_missing_measurements", []) or []),
        "missing_measurements_names": merge_dq.get("rooms_with_missing_measurements", []),
    }


def _extract_pipeline_health(observations: dict) -> dict:
    """Check which pipeline nodes completed and find errors."""
    completed = [n for n in EXPECTED_NODES if n in observations]
    has_assembly = "Assembly" in observations or "Translation" in observations

    error_node = None
    error_type = None
    for name, obs in observations.items():
        level = getattr(obs, "level", None)
        if level and hasattr(level, "value") and level.value == "ERROR":
            if name not in ("flow", "PromptFlowExecutor.exec",
                            "POST /v1/mitigation-scopes"):
                error_node = name
                error_type = (obs.status_message or "")[:200]
                break

    return {
        "complete": has_assembly,
        "completed_nodes": completed,
        "missing_nodes": [n for n in EXPECTED_NODES if n not in observations],
        "error_node": error_node,
        "error_type": error_type,
    }


def _extract_qualitative_data(trace, observations: dict) -> dict:
    """Extract qualitative data for LLM narrative generation."""
    result: dict = {
        "photo_agg_data": "Not available",
        "data_quality_notes": "Not available",
        "org_room_findings": [],
    }

    # PropertyImagesAggregator output
    pia = observations.get("PropertyImagesAggregator")
    if pia and pia.output:
        output = pia.output
        if isinstance(output, dict):
            rooms_data = output.get("rooms", [])
            photo_summary = []
            for r in rooms_data[:20]:  # Cap at 20 rooms
                name = r.get("room_name", "?")
                count = r.get("photo_count", 0)
                photo_summary.append(f"{name}: {count} photos")
            result["photo_agg_data"] = "; ".join(photo_summary) if photo_summary else "No room-level photo data"
        elif isinstance(output, list):
            # Per-photo list format
            summaries = []
            for item in output[:30]:  # Cap at 30 photos
                rooms = item.get("rooms", [])
                relevance = item.get("damage_relevance", "?")
                temporal = item.get("temporal_classification", "?")
                room_names = [r.get("room_name", "?") for r in rooms[:3]]
                summaries.append(
                    f"rooms={','.join(room_names)} relevance={relevance} "
                    f"temporal={temporal}"
                )
            result["photo_agg_data"] = "\n".join(summaries) if summaries else "Empty"

    # Assembly Data Quality Notes section
    assembly = observations.get("Assembly")
    if assembly and assembly.output:
        scope_text = ""
        if isinstance(assembly.output, dict):
            scope_text = assembly.output.get("scope", "")
        elif isinstance(assembly.output, str):
            scope_text = assembly.output

        dq_match = re.search(
            r"## Data Quality Notes\n(.*?)(?=\n## |\Z)",
            scope_text, re.DOTALL,
        )
        if dq_match:
            result["data_quality_notes"] = dq_match.group(1).strip()[:2000]

    # Organizational room findings from Merge
    merge = observations.get("Merge")
    if merge and merge.output and isinstance(merge.output, dict):
        findings = merge.output.get("organizational_room_findings", [])
        result["org_room_findings"] = findings[:10] if findings else []

    return result


def _extract_issue_data(observations: dict) -> dict:
    """Extract all data_quality objects from Merge, Tasks, Drying."""
    issues: dict[str, list] = {
        "iicrc_conflicts": [],
        "material_conflicts": [],
        "measurement_warnings": [],
        "rooms_with_missing_measurements": [],
        "affected_rooms_without_photos": [],
        "scope_conflicts": [],
        "material_mismatches": [],
        "factor_conflicts": [],
    }

    merge = observations.get("Merge")
    if merge and merge.output and isinstance(merge.output, dict):
        dq = merge.output.get("data_quality", {})
        if isinstance(dq, dict):
            issues["iicrc_conflicts"] = dq.get("iicrc_conflicts", [])
            issues["material_conflicts"] = dq.get("material_conflicts", [])
            issues["measurement_warnings"] = dq.get("measurement_warnings", [])
            issues["rooms_with_missing_measurements"] = dq.get(
                "rooms_with_missing_measurements", []
            )
            issues["affected_rooms_without_photos"] = dq.get(
                "affected_rooms_without_photos", []
            )

    tasks = observations.get("Tasks")
    if tasks and tasks.output and isinstance(tasks.output, dict):
        dq = tasks.output.get("data_quality", {})
        if isinstance(dq, dict):
            issues["scope_conflicts"] = dq.get("scope_conflicts", [])
            issues["material_mismatches"] = dq.get("material_mismatches", [])

    drying = observations.get("Drying")
    if drying and drying.output and isinstance(drying.output, dict):
        dq = drying.output.get("data_quality", {})
        if isinstance(dq, dict):
            issues["factor_conflicts"] = dq.get("factor_conflicts", [])

    return issues


# ── Scoring ───────────────────────────────────────────────────────


def _score_input(input_stats: dict, room_stats: dict) -> tuple[int, str, bool]:
    """Score input quality 1-5. Returns (score, label, is_initial_scope)."""
    photo_count = input_stats.get("photo_count", 0)
    note_count = input_stats.get("note_count", 0)
    floor_plan_count = input_stats.get("floor_plan_count", 0)
    affected = room_stats.get("affected", 1) or 1
    total = room_stats.get("total", 1) or 1

    # Initial scope detection: note(s) with nothing else
    is_initial_scope = (
        note_count >= 1
        and photo_count == 0
        and floor_plan_count == 0
    )

    points = 0.0

    # Photos (0-2 pts)
    if photo_count >= 15:       points += 2.0
    elif photo_count >= 5:      points += 1.5
    elif photo_count > 0:       points += 1.0

    # Technician Notes (0-1.5 pts)
    if note_count >= 3:         points += 1.5
    elif note_count >= 1:       points += 1.0

    # Floor Plans (0-1 pt)
    if floor_plan_count >= 1 and room_stats.get("with_measurements", 0) > 0:
        points += 1.0
    elif floor_plan_count >= 1:
        points += 0.5

    # Room Setup (0-0.5 pt)
    if room_stats.get("from_app", 0) > total * 0.5:
        points += 0.5

    # Moisture/Hydro Data (0-0.5 pt)
    if input_stats.get("has_moisture", False):
        points += 0.5

    # Coverage gap penalties
    rooms_without_photos = room_stats.get("rooms_without_photos", 0)
    rooms_without_notes = room_stats.get("rooms_without_notes", 0)
    if affected > 0:
        if rooms_without_photos > 0 and photo_count > 0:
            gap_pct = rooms_without_photos / max(affected, 1)
            points -= gap_pct * 0.5
        if rooms_without_notes > 0 and note_count > 0:
            gap_pct = rooms_without_notes / max(affected, 1)
            points -= gap_pct * 0.25

    # Map points (max ~7.5) to 1-5 scale
    scaled = 1 + (points / 7.5) * 4
    score = max(1, min(5, round(scaled)))

    # Initial scope boost
    if is_initial_scope and note_count >= 1:
        score = max(score, 3)

    return score, _INPUT_LABELS[score], is_initial_scope


def _score_pipeline(
    trace_data: TraceData, health: dict, room_stats: dict
) -> tuple[int, str]:
    """Score pipeline health 1-5."""
    if trace_data.output_is_null:
        if health.get("error_node"):
            return 1, _PIPELINE_LABELS[1]
        return 2, _PIPELINE_LABELS[2]

    warnings = 0
    if room_stats.get("rooms_without_photos", 0) > 0:
        warnings += 1
    if room_stats.get("rooms_without_notes", 0) > 0:
        warnings += 1
    if room_stats.get("rooms_may_be_missing", False):
        warnings += 1
    if room_stats.get("discrepancy_sf", 0) > 50:
        warnings += 1
    if room_stats.get("unmatched_fp_rooms", 0) > 0:
        warnings += 1

    if warnings >= 3:
        return 3, _PIPELINE_LABELS[3]
    if warnings >= 1:
        return 4, _PIPELINE_LABELS[4]
    return 5, _PIPELINE_LABELS[5]


def _score_issues(issue_data: dict) -> tuple[int, str]:
    """Score data quality issues 1-5 based on severity counts."""
    high = 0
    medium = 0
    low = 0

    # Classify conflicts by severity field
    for key in (
        "iicrc_conflicts", "scope_conflicts", "material_conflicts",
        "factor_conflicts", "material_mismatches",
    ):
        for item in issue_data.get(key, []):
            sev = (item.get("severity") or "low").lower() if isinstance(item, dict) else "low"
            if sev == "high":
                high += 1
            elif sev == "medium":
                medium += 1
            else:
                low += 1

    # Simple list items count as low severity
    low += len(issue_data.get("measurement_warnings", []))
    low += len(issue_data.get("rooms_with_missing_measurements", []))
    low += len(issue_data.get("affected_rooms_without_photos", []))

    if high >= 2:
        score = 1
    elif high >= 1 or medium >= 3:
        score = 2
    elif medium >= 1 or low >= 3:
        score = 3
    elif low >= 1:
        score = 4
    else:
        score = 5

    return score, _ISSUE_LABELS[score]


# ── LLM Narrative ────────────────────────────────────────────────


def _generate_narrative(
    report: TraceEvalReport,
    input_stats: dict,
    room_stats: dict,
    qualitative: dict,
    llm_client,
    issue_data: dict | None = None,
) -> dict:
    """Call LLM to generate Input/Pipeline/Issue Assessment + Recommendations."""
    minutes = int(report.latency // 60)
    seconds = int(report.latency % 60)

    stats_json = json.dumps({
        "processing_time": f"{minutes}m {seconds}s",
        "total_rooms": report.total_rooms,
        "affected_rooms": report.affected_rooms,
        "unaffected_rooms": report.unaffected_rooms,
        "rooms_from_app": report.rooms_from_app,
        "rooms_from_description": report.rooms_from_description,
        "rooms_with_measurements": report.rooms_with_measurements,
        "pipeline_complete": report.pipeline_complete,
        "input_score": f"{report.input_score}/5 {report.input_label}",
        "pipeline_score": f"{report.pipeline_score}/5 {report.pipeline_label}",
        "issue_score": f"{report.issue_score}/5 {report.issue_label}",
    }, indent=2)

    prompt = HAIKU_PROMPT.format(
        stats_json=stats_json,
        photo_count=report.photo_count,
        photo_agg_data=qualitative.get("photo_agg_data", "Not available"),
        rooms_without_photos=_format_room_list(
            room_stats.get("affected_rooms_without_photos_list", [])
        ),
        rooms_with_few_photos=str(report.rooms_with_few_photos),
        photo_damage_discrepancies=_format_list(
            room_stats.get("photo_damage_in_unaffected", [])
        ),
        note_count=report.note_count,
        note_snippets=_format_note_snippets(input_stats.get("note_snippets", [])),
        rooms_without_notes_detail=_format_room_quality_list(
            room_stats.get("rooms_without_notes_detail", [])
        ),
        insufficient_notes_detail=_format_room_quality_list(
            room_stats.get("rooms_with_insufficient_notes", [])
        ),
        room_source_breakdown=(
            f"{report.rooms_from_app} from app, "
            f"{report.rooms_from_description} from notes, "
            f"{report.total_rooms - report.rooms_from_app - report.rooms_from_description} other"
        ),
        org_room_findings=_format_list(qualitative.get("org_room_findings", [])),
        room_names_list=_format_room_names(room_stats.get("room_names", [])),
        floor_plan_count=report.floor_plan_count,
        matched_by_name=_format_room_list(room_stats.get("matched_by_name", [])),
        matched_by_id=_format_room_list(room_stats.get("matched_by_id", [])),
        unmatched_fp_rooms=_format_room_list(
            room_stats.get("unmatched_fp_rooms_list", [])
        ),
        missing_measurements=_format_room_list(
            room_stats.get("missing_measurements_list", [])
        ),
        discrepancy_sf=f"{room_stats.get('discrepancy_sf', 0):.0f}",
        discrepancy_pct=f"{room_stats.get('discrepancy_pct', 0):.1f}",
        room_matching_details=_format_validation_matching(
            room_stats.get("validation", {})
        ),
        unmatched_claim_rooms=_format_list(
            room_stats.get("validation", {}).get("missing_rooms", [])
        ),
        data_quality_notes_section=qualitative.get(
            "data_quality_notes", "Not available"
        ),
        issue_data_section=_format_issue_data_for_prompt(issue_data or {}),
    )

    response = llm_client.messages.create(
        model=os.environ.get("EVAL_MODEL", "claude-haiku-4-5-20251001"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1500,
    )

    text = response.content[0].text if response.content else ""

    # Parse four sections
    input_match = re.search(
        r"### Input Assessment\n(.*?)(?=### Pipeline Assessment|\Z)",
        text, re.DOTALL,
    )
    pipeline_match = re.search(
        r"### Pipeline Assessment\n(.*?)(?=### Issue Assessment|\Z)",
        text, re.DOTALL,
    )
    issue_match = re.search(
        r"### Issue Assessment\n(.*?)(?=### Recommendations|\Z)",
        text, re.DOTALL,
    )
    recs_match = re.search(
        r"### Recommendations\n(.*?)$", text, re.DOTALL,
    )

    return {
        "input_assessment": input_match.group(1).strip() if input_match else text,
        "pipeline_assessment": pipeline_match.group(1).strip() if pipeline_match else "",
        "issue_assessment": issue_match.group(1).strip() if issue_match else "",
        "recommendations": recs_match.group(1).strip() if recs_match else "",
    }


# ── Formatting helpers ────────────────────────────────────────────


def _format_room_list(items: list) -> str:
    if not items:
        return "None"
    if isinstance(items[0], str):
        return ", ".join(items[:15])
    return ", ".join(str(i) for i in items[:15])


def _format_list(items: list) -> str:
    if not items:
        return "None"
    return json.dumps(items[:10], default=str)


def _format_note_snippets(snippets: list[str]) -> str:
    if not snippets:
        return "No notes found"
    parts = []
    for i, s in enumerate(snippets[:10], 1):
        parts.append(f"Note {i}: {s}")
    return "\n".join(parts)


def _format_room_quality_list(items: list) -> str:
    if not items:
        return "None"
    parts = []
    for item in items[:10]:
        if isinstance(item, dict):
            name = item.get("room_name", "?")
            issue = item.get("quality_issue", item.get("note_word_count", ""))
            parts.append(f"{name} ({issue})")
        else:
            parts.append(str(item))
    return ", ".join(parts)


def _format_room_names(rooms: list[dict]) -> str:
    if not rooms:
        return "No rooms"
    parts = []
    for r in rooms[:20]:
        status = "affected" if r.get("affected") else "unaffected"
        parts.append(f"{r.get('room_name', '?')} ({r.get('floor_name', '?')}) [{status}]")
    return "; ".join(parts)


def _format_validation_matching(validation: dict) -> str:
    matching = validation.get("room_matching", [])
    if not matching:
        return "No matching data"
    parts = []
    for m in matching[:15]:
        if isinstance(m, dict):
            parts.append(
                f"{m.get('room_name', '?')}: {m.get('match_method', '?')}"
            )
    return "; ".join(parts) if parts else "No matching data"


# ── Fallback templates (no LLM) ──────────────────────────────────


def _fallback_input_summary(r: TraceEvalReport) -> str:
    """Generate template-based input summary when LLM is unavailable."""
    parts = []

    if r.photo_count == 0:
        parts.append("No field photos were submitted for this scope.")
    elif r.photo_count < 5:
        parts.append(
            f"Only {r.photo_count} photos were submitted, which limits "
            "the system's ability to verify damage in each room."
        )
    else:
        parts.append(f"{r.photo_count} field photos were submitted.")

    if r.note_count == 0:
        parts.append(
            "No technician notes were included, so the scope relied "
            "entirely on photos and floor plans for damage details."
        )
    elif r.note_count < r.affected_rooms:
        parts.append(
            f"Notes were provided for some rooms ({r.note_count} notes "
            f"across {r.affected_rooms} affected rooms), but not all "
            "rooms had written descriptions of the damage."
        )
    else:
        parts.append(f"Technician notes were provided ({r.note_count} notes).")

    if r.floor_plan_count == 0:
        parts.append(
            "No floor plans were uploaded, so room measurements are not "
            "available and task quantities will need to be filled in manually."
        )
    elif r.rooms_with_measurements == 0:
        parts.append(
            f"{r.floor_plan_count} floor plan(s) were uploaded but room "
            "labels could not be matched, so measurements could not be "
            "assigned to specific rooms."
        )
    else:
        if r.affected_rooms:
            pct = round(r.rooms_with_measurements / r.affected_rooms * 100)
        else:
            pct = 0
        parts.append(
            f"{r.floor_plan_count} floor plan(s) provided with "
            f"measurements assigned to {pct}% of affected rooms."
        )

    if r.unmatched_floor_plan_rooms > 0:
        parts.append(
            f"{r.unmatched_floor_plan_rooms} floor plan room(s) could not "
            "be matched to claim rooms because the names didn't match. "
            "Make sure floor plan room labels match claim room names before "
            "running the scope."
        )

    if r.rooms_from_app == 0 and r.total_rooms > 0:
        parts.append(
            "Rooms were not set up in the app before running the scope, "
            "which means they will not sync back to the field application."
        )
    elif r.rooms_from_app < r.total_rooms:
        parts.append(
            f"{r.rooms_from_app} of {r.total_rooms} rooms were set up "
            "in the app beforehand."
        )

    if r.has_moisture:
        parts.append("Moisture readings were included.")
    elif r.affected_rooms > 0:
        parts.append("No moisture monitoring data was submitted.")

    return " ".join(parts)


def _fallback_pipeline_summary(r: TraceEvalReport) -> str:
    """Generate template-based pipeline summary when LLM is unavailable."""
    minutes = int(r.latency // 60)
    seconds = int(r.latency % 60)
    parts = []

    if r.pipeline_complete:
        parts.append(
            f"The scope completed successfully in {minutes}m {seconds}s."
        )
    else:
        parts.append(f"The scope failed after {minutes}m {seconds}s.")
        if r.error_node:
            parts.append(
                f"The failure occurred at the {r.error_node} step "
                f"({r.error_type or 'unknown error'})."
            )
        parts.append(
            f"{len(r.nodes_completed)} of {len(EXPECTED_NODES)} "
            "processing steps completed before the failure."
        )
        return " ".join(parts)

    issues = []
    if r.rooms_without_photos > 0:
        issues.append(
            f"{r.rooms_without_photos} affected room(s) had no photos"
        )
    if r.rooms_without_notes > 0:
        issues.append(
            f"{r.rooms_without_notes} affected room(s) had no technician notes"
        )
    if r.rooms_may_be_missing:
        issues.append(
            f"the floor plan area differs from room areas by "
            f"{r.floor_plan_discrepancy_sf:.0f} SF"
        )
    if r.unmatched_floor_plan_rooms > 0:
        issues.append(
            f"{r.unmatched_floor_plan_rooms} floor plan room(s) could not "
            "be matched to claim rooms"
        )

    if issues:
        parts.append("Data quality flags: " + "; ".join(issues) + ".")
    else:
        parts.append("No data quality issues were flagged.")

    return " ".join(parts)


def _fallback_issue_summary(issue_data: dict) -> str:
    """Template-based issue summary when LLM is unavailable."""
    total = sum(len(v) for v in issue_data.values())
    if total == 0:
        return "No data quality issues were detected in this scope."

    parts = []
    if issue_data.get("iicrc_conflicts"):
        n = len(issue_data["iicrc_conflicts"])
        parts.append(f"{n} IICRC standard deviation(s) were flagged")
    if issue_data.get("scope_conflicts"):
        n = len(issue_data["scope_conflicts"])
        parts.append(f"{n} scope conflict(s) were identified")
    if issue_data.get("material_conflicts"):
        n = len(issue_data["material_conflicts"])
        parts.append(f"{n} material discrepancy(ies) between photos and descriptions")
    if issue_data.get("material_mismatches"):
        n = len(issue_data["material_mismatches"])
        parts.append(f"{n} material mismatch(es) between room data sources")
    if issue_data.get("factor_conflicts"):
        n = len(issue_data["factor_conflicts"])
        parts.append(f"{n} equipment sizing conflict(s)")
    if issue_data.get("measurement_warnings"):
        n = len(issue_data["measurement_warnings"])
        parts.append(f"{n} measurement validation warning(s)")
    if issue_data.get("rooms_with_missing_measurements"):
        n = len(issue_data["rooms_with_missing_measurements"])
        parts.append(f"{n} room(s) with missing measurements")
    if issue_data.get("affected_rooms_without_photos"):
        n = len(issue_data["affected_rooms_without_photos"])
        parts.append(f"{n} affected room(s) without photos")

    return f"The system detected {total} data quality issue(s): " + "; ".join(parts) + "."


def _fallback_recommendations(r: TraceEvalReport, issue_data: dict) -> str:
    """Template-based recommendations when LLM is unavailable."""
    recs = []

    if r.photo_count == 0:
        recs.append(
            "Take photos of each affected room before running the scope. "
            "Photos help verify damage type and extent in each room."
        )
    elif r.rooms_without_photos > 0:
        recs.append(
            f"Add photos for the {r.rooms_without_photos} room(s) that are "
            "missing them. Each room should have at least a few photos "
            "showing the damage."
        )

    if r.note_count == 0:
        recs.append(
            "Add technician notes describing the damage in each room. "
            "Notes provide details that photos alone cannot capture, "
            "like the source of water or hidden damage."
        )
    elif r.rooms_without_notes > 0:
        recs.append(
            f"Add notes for the {r.rooms_without_notes} room(s) missing them. "
            "Even brief notes about damage type and extent help."
        )

    if r.floor_plan_count == 0:
        recs.append(
            "Upload a floor plan with room measurements. Without measurements, "
            "task quantities cannot be calculated and must be filled in manually."
        )
    elif r.unmatched_floor_plan_rooms > 0:
        recs.append(
            "Check that floor plan room labels match the room names in your "
            "claim. Mismatched names prevent measurements from being assigned."
        )

    if r.rooms_from_app == 0 and r.total_rooms > 0:
        recs.append(
            "Set up rooms in the app before running the scope. Rooms created "
            "in the app sync back to your field application; rooms inferred "
            "from notes do not."
        )

    if issue_data.get("iicrc_conflicts"):
        recs.append(
            "Review the IICRC standard deviations flagged in this scope. "
            "These may indicate that the water category or class needs "
            "to be re-evaluated."
        )

    if not recs:
        return (
            "This scope had good input data and no significant issues. "
            "Continue providing detailed notes, photos, and floor plans "
            "for consistent results."
        )

    return "\n".join(f"{i}. {rec}" for i, rec in enumerate(recs, 1))


def _format_issue_data_for_prompt(issue_data: dict) -> str:
    """Format structured issue data for the LLM prompt."""
    sections = []
    for key, items in issue_data.items():
        if items:
            label = key.replace("_", " ").title()
            sections.append(f"{label} ({len(items)}):")
            for item in items[:5]:
                if isinstance(item, dict):
                    sections.append(f"  - {json.dumps(item, default=str)}")
                else:
                    sections.append(f"  - {item}")
    return "\n".join(sections) if sections else "No data quality issues found."
