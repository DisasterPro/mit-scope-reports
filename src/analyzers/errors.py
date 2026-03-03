"""Error analysis -- replicates the /se skill."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from ..langfuse_client import LangfuseDataFetcher
from ..models import (
    AffectedUser,
    ErrorReport,
    ErrorTrace,
    ErrorTypeGroup,
    TraceData,
)

logger = logging.getLogger(__name__)

# These observations propagate errors from children -- not root causes
CASCADE_NAMES = frozenset({
    "flow",
    "PromptFlowExecutor.exec",
    "POST /v1/mitigation-scopes",
})

# LLM call SPANs -- not pipeline nodes. If an ERROR is on one of these,
# the real failing node is the parent pipeline node.
LLM_SPAN_NAMES = frozenset({
    "openai_chat",
    "openai_chat_async",
    "OpenAI-generation",
})

CONTENT_FILTER_TYPES = {
    "sexual": "Sexual",
    "self_harm": "Self-Harm",
    "violence": "Violence",
    "hate": "Hate",
    "profanity": "Profanity",
}


def analyze_errors(
    traces: list[TraceData],
    fetcher: LangfuseDataFetcher,
) -> ErrorReport:
    """Identify and classify production errors from traces."""
    total_production = len(traces)

    # Step 1: Find candidate error traces (output is null)
    candidates = [t for t in traces if t.output_is_null]
    logger.info("Found %d candidate error traces out of %d total", len(candidates), total_production)

    # Step 2: Verify each candidate (guard against compact-mode false positives)
    confirmed_errors: list[TraceData] = []
    for t in candidates:
        if fetcher.verify_null_output(t.id):
            confirmed_errors.append(t)
        else:
            logger.info("Trace %s: false positive (output not truly null)", t.id)

    logger.info("Confirmed %d error traces", len(confirmed_errors))

    # Step 3: Fetch observations and classify each error
    error_traces: list[ErrorTrace] = []
    for t in confirmed_errors:
        observations = fetcher.fetch_observations(t.id)
        error_info = _classify_error(observations)

        error_traces.append(
            ErrorTrace(
                trace_id=t.id,
                user_id=t.user_id,
                timestamp=t.timestamp,
                total_cost=t.total_cost,
                latency=t.latency,
                error_type=error_info["error_type"],
                failing_node=error_info["failing_node"],
                filter_type=error_info.get("filter_type"),
                status_message=error_info.get("status_message", ""),
                pipeline_completeness=error_info.get("pipeline_completeness", ""),
            )
        )

    # Step 4: Group errors by type + node
    group_key_map: dict[tuple[str, str, str | None], list[ErrorTrace]] = defaultdict(list)
    for et in error_traces:
        key = (et.error_type, et.failing_node, et.filter_type)
        group_key_map[key].append(et)

    error_groups: list[ErrorTypeGroup] = []
    for (error_type, node, filter_type), group_traces in group_key_map.items():
        error_groups.append(
            ErrorTypeGroup(
                error_type=error_type,
                node=node,
                count=len(group_traces),
                filter_type=filter_type,
                traces=group_traces,
            )
        )

    error_groups.sort(key=lambda g: g.count, reverse=True)

    # Step 5: Affected users
    user_errors: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for et in error_traces:
        email = et.user_id or "unknown"
        user_errors[email][et.error_type] += 1

    affected_users: list[AffectedUser] = []
    for email, type_counts in user_errors.items():
        total = sum(type_counts.values())
        types_str = ", ".join(
            f"{t} ({c})" if c > 1 else t for t, c in sorted(type_counts.items())
        )
        affected_users.append(
            AffectedUser(email=email, error_count=total, error_types=types_str)
        )

    affected_users.sort(key=lambda u: u.error_count, reverse=True)

    total_errors = len(error_traces)
    error_rate = (total_errors / total_production * 100) if total_production else 0.0

    return ErrorReport(
        total_production=total_production,
        total_errors=total_errors,
        error_rate=error_rate,
        error_groups=error_groups,
        affected_users=affected_users,
    )


def _classify_error(observations: list[dict]) -> dict:
    """Classify the root cause error from a trace's observations."""
    # Find primary ERROR observation (not cascade, not raw LLM SPAN)
    primary_error = None
    fallback_error = None
    for obs in observations:
        if obs.get("level") != "ERROR":
            continue
        name = obs.get("name", "")
        if name in CASCADE_NAMES:
            continue
        if name in LLM_SPAN_NAMES:
            # Keep as fallback if no pipeline node ERROR found
            if fallback_error is None:
                fallback_error = obs
            continue
        primary_error = obs
        break

    if not primary_error:
        primary_error = fallback_error

    if not primary_error:
        # No ERROR observation found -- classify as Unknown
        completed_nodes = [
            obs.get("name", "?")
            for obs in observations
            if obs.get("level") != "ERROR" and obs.get("name") not in CASCADE_NAMES
        ]
        return {
            "error_type": "Unknown",
            "failing_node": "Unknown",
            "status_message": "No ERROR observation found",
            "pipeline_completeness": ", ".join(completed_nodes) if completed_nodes else "None",
        }

    node_name = primary_error.get("name", "Unknown")
    status_msg = primary_error.get("status_message", "") or ""

    # If the primary error is on an LLM SPAN, try to find the pipeline node name
    # from the cascade error message (e.g., "Execution failure in 'Description'")
    if node_name in LLM_SPAN_NAMES:
        for obs in observations:
            if obs.get("level") == "ERROR" and obs.get("name") in CASCADE_NAMES:
                msg = obs.get("status_message", "") or ""
                # Extract node name from "Execution failure in 'NodeName'"
                match = re.search(r"failure in '(\w+)'", msg)
                if match:
                    node_name = match.group(1)
                    break

    # Classify by error content
    if "content_filter" in status_msg.lower() or "premature completion" in status_msg.lower():
        filter_type = _detect_filter_type(observations, node_name, status_msg)
        return {
            "error_type": "ContentFilterCompletion",
            "failing_node": node_name,
            "filter_type": filter_type,
            "status_message": status_msg[:200],
        }

    if "ValueError" in status_msg or "value error" in status_msg.lower():
        return {
            "error_type": "ValueError",
            "failing_node": node_name,
            "status_message": status_msg[:200],
        }

    if "AttributeError" in status_msg:
        return {
            "error_type": "AttributeError",
            "failing_node": node_name,
            "status_message": status_msg[:200],
        }

    if "TemplateSyntaxError" in status_msg or "template" in status_msg.lower():
        return {
            "error_type": "TemplateSyntaxError",
            "failing_node": node_name,
            "status_message": status_msg[:200],
        }

    return {
        "error_type": "Other",
        "failing_node": node_name,
        "status_message": status_msg[:200],
    }


def _detect_filter_type(
    observations: list[dict], node_name: str, status_msg: str
) -> str:
    """Detect the specific content filter type from OpenAI SPAN output."""
    # Check if this is a prompt-level rejection (BadRequestError 400)
    if "BadRequestError" in status_msg and "400" in status_msg:
        return "Prompt Rejected"

    # Find the corresponding openai_chat or openai_chat_async SPAN
    for obs in observations:
        obs_name = obs.get("name", "")
        if obs_name not in ("openai_chat", "openai_chat_async"):
            continue

        # Check if this SPAN belongs to the same node
        metadata = obs.get("metadata") or {}
        if isinstance(metadata, dict):
            obs_node = metadata.get("node_name", "")
            if obs_node and obs_node != node_name:
                continue

        # Check output for filter results
        output = obs.get("output")
        if not isinstance(output, dict):
            continue

        choices = output.get("choices", [])
        if not choices:
            continue

        filter_results = choices[0].get("content_filter_results", {})
        if not isinstance(filter_results, dict):
            continue

        for filter_key, display_name in CONTENT_FILTER_TYPES.items():
            result = filter_results.get(filter_key, {})
            if isinstance(result, dict) and result.get("filtered"):
                return display_name

    return "Unknown"
