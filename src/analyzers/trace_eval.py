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

Write exactly two sections in markdown:

### Input Assessment
1-2 paragraphs covering:
- What was provided and how well organized (photos labeled to right rooms?
  notes detailed or generic? rooms set up in app or inferred?)
- Specific gaps found (rooms without photos, rooms without notes, etc.)
- Room name matching issues if any (floor plan names vs claim names)
- 2-3 actionable recommendations for next time, explaining WHY each matters

### Pipeline Assessment
1 paragraph covering:
- Processing time and whether it completed successfully
- Any data quality issues the system detected (missing measurements,
  photo-damage mismatches, organizational rooms, etc.)
- Do NOT mention cost
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

    # --- Extract stats ---
    input_stats = _extract_input_stats(trace)
    room_stats = _extract_room_stats(observations)
    pipeline_health = _extract_pipeline_health(observations)
    qualitative = _extract_qualitative_data(trace, observations)

    # --- Score ---
    input_score, input_label = _score_input(input_stats, room_stats)
    pipeline_score, pipeline_label = _score_pipeline(
        trace_data, pipeline_health, room_stats,
    )

    report = TraceEvalReport(
        trace_id=trace_data.id,
        timestamp=trace_data.timestamp,
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
        rooms_without_photos=room_stats.get("rooms_without_photos", 0),
        rooms_without_notes=room_stats.get("rooms_without_notes", 0),
        rooms_with_few_photos=room_stats.get("rooms_with_few_photos", 0),
        floor_plan_discrepancy_sf=room_stats.get("discrepancy_sf", 0.0),
        rooms_may_be_missing=room_stats.get("rooms_may_be_missing", False),
        unmatched_floor_plan_rooms=room_stats.get("unmatched_fp_rooms", 0),
        input_score=input_score,
        input_label=input_label,
        pipeline_score=pipeline_score,
        pipeline_label=pipeline_label,
    )

    # --- Generate narrative via LLM ---
    if llm_client:
        try:
            narrative = _generate_narrative(
                report, input_stats, room_stats, qualitative, llm_client,
            )
            report.input_assessment = narrative.get("input_assessment", "")
            report.pipeline_assessment = narrative.get("pipeline_assessment", "")
        except Exception:
            logger.exception("LLM narrative generation failed for %s", trace_data.id)
            report.input_assessment = _fallback_input_summary(report)
            report.pipeline_assessment = _fallback_pipeline_summary(report)
    else:
        report.input_assessment = _fallback_input_summary(report)
        report.pipeline_assessment = _fallback_pipeline_summary(report)

    return report


# ── Extraction ────────────────────────────────────────────────────


def _extract_input_stats(trace) -> dict:
    """Extract input stats from trace.input."""
    if not trace or not trace.input:
        return {}

    inp = trace.input if isinstance(trace.input, dict) else {}
    description = inp.get("description", "") or ""

    return {
        "photo_count": len(inp.get("property_images", []) or []),
        "floor_plan_count": len(inp.get("measurement_images", []) or []),
        "note_count": description.count("<NOTE>"),
        "has_guidelines": bool(inp.get("guidelines")),
        "has_moisture": "moisture_monitoring" in description.lower(),
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
    with_meas = sum(1 for r in rooms if r.get("measurements_available", False))

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


# ── Scoring ───────────────────────────────────────────────────────


def _score_input(input_stats: dict, room_stats: dict) -> tuple[int, str]:
    """Score input quality 1-5."""
    points = 0.0
    photo_count = input_stats.get("photo_count", 0)
    note_count = input_stats.get("note_count", 0)
    floor_plan_count = input_stats.get("floor_plan_count", 0)
    affected = room_stats.get("affected", 1) or 1
    total = room_stats.get("total", 1) or 1

    if photo_count >= 10:
        points += 2
    elif photo_count >= 1:
        points += 1

    if note_count >= affected:
        points += 1
    elif note_count >= 1:
        points += 0.5

    if floor_plan_count >= 1 and room_stats.get("with_measurements", 0) > 0:
        points += 1
    elif floor_plan_count >= 1:
        points += 0.5

    if input_stats.get("has_moisture", False):
        points += 0.5

    if room_stats.get("from_app", 0) > total * 0.5:
        points += 0.5

    score = max(1, min(5, round(points + 0.5)))
    return score, _INPUT_LABELS[score]


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


# ── LLM Narrative ────────────────────────────────────────────────


def _generate_narrative(
    report: TraceEvalReport,
    input_stats: dict,
    room_stats: dict,
    qualitative: dict,
    llm_client,
) -> dict:
    """Call LLM to generate Input Assessment and Pipeline Assessment."""
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
    )

    response = llm_client.chat.completions.create(
        model=os.environ.get("EVAL_LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000,
    )

    text = response.choices[0].message.content or ""

    # Parse the two sections
    input_match = re.search(
        r"### Input Assessment\n(.*?)(?=### Pipeline Assessment|\Z)",
        text, re.DOTALL,
    )
    pipeline_match = re.search(
        r"### Pipeline Assessment\n(.*?)$", text, re.DOTALL,
    )

    return {
        "input_assessment": input_match.group(1).strip() if input_match else text,
        "pipeline_assessment": pipeline_match.group(1).strip() if pipeline_match else "",
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
