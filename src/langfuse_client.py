"""Langfuse API client for fetching production trace data.

Uses the Langfuse Python SDK's REST client directly to paginate
through traces and fetch observation details for error analysis.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from langfuse.api.client import FernLangfuse
from langfuse.api import ObservationLevel

from .models import TraceData

logger = logging.getLogger(__name__)

# Internal domains excluded from all reports (internal testing)
EXCLUDED_DOMAINS = {"encircleapp.com"}


def _is_internal_user(user_id: str | None) -> bool:
    """Check if a user belongs to an excluded internal domain."""
    if not user_id:
        return False
    domain = user_id.rsplit("@", 1)[-1].lower()
    return domain in EXCLUDED_DOMAINS


class LangfuseDataFetcher:
    """Fetches production traces from Langfuse for a given time window."""

    def __init__(self, host: str, public_key: str, secret_key: str):
        self._client = FernLangfuse(
            base_url=host,
            username=public_key,
            password=secret_key,
            timeout=60.0,
        )

    def fetch_all_production_traces(
        self, from_ts: datetime, to_ts: datetime
    ) -> list[TraceData]:
        """Paginate through all production traces in the time window.

        Filters server-side by environment="production", then post-filters
        to exclude experiment traces.
        """
        all_traces: list[TraceData] = []
        page = 1

        while True:
            logger.info("Fetching traces page %d...", page)
            response = self._client.trace.list(
                page=page,
                limit=100,
                from_timestamp=from_ts,
                to_timestamp=to_ts,
                environment="production",
            )

            for t in response.data:
                # Exclude eval experiment traces
                if t.name == "experiment-item-run":
                    continue

                all_traces.append(
                    TraceData(
                        id=t.id,
                        timestamp=t.timestamp,
                        user_id=t.user_id,
                        total_cost=t.total_cost or 0.0,
                        latency=t.latency or 0.0,
                        name=t.name,
                        output_is_null=(t.output is None),
                    )
                )

            total_pages = response.meta.total_pages if response.meta.total_pages else 1
            logger.info(
                "Page %d: got %d traces (total pages: %d)",
                page,
                len(response.data),
                total_pages,
            )

            if page >= total_pages or len(response.data) < 100:
                break

            page += 1
            time.sleep(0.1)  # Rate limit courtesy

        # Exclude internal test users
        before_filter = len(all_traces)
        all_traces = [t for t in all_traces if not _is_internal_user(t.user_id)]
        excluded = before_filter - len(all_traces)
        if excluded:
            logger.info("Excluded %d internal traces", excluded)

        logger.info("Total production traces fetched: %d", len(all_traces))
        return all_traces

    def verify_null_output(self, trace_id: str) -> bool:
        """Verify that a trace's output is truly null.

        The list endpoint may truncate output in compact mode,
        so we fetch the full trace to confirm.
        """
        time.sleep(0.5)  # Rate limit courtesy
        try:
            trace = self._client.trace.get(trace_id=trace_id)
            is_null = trace.output is None
            logger.debug("Trace %s output is null: %s", trace_id, is_null)
            return is_null
        except Exception:
            logger.warning("Failed to verify trace %s, assuming error", trace_id)
            return True

    def fetch_trace_full(self, trace_id: str) -> dict:
        """Fetch full trace + observations with outputs for eval analysis.

        Returns a dict with 'trace' (full trace object) and 'observations'
        (dict keyed by observation name, first per name wins).
        """
        time.sleep(0.5)
        try:
            trace = self._client.trace.get(trace_id=trace_id)
            obs_response = self._client.observations.get_many(
                trace_id=trace_id, limit=100,
            )
            obs_by_name: dict[str, object] = {}
            for obs in obs_response.data:
                if obs.name and obs.name not in obs_by_name:
                    obs_by_name[obs.name] = obs
            logger.info(
                "Trace %s: fetched full trace + %d observations",
                trace_id, len(obs_by_name),
            )
            return {"trace": trace, "observations": obs_by_name}
        except Exception:
            logger.exception("Failed to fetch full trace %s", trace_id)
            return {"trace": None, "observations": {}}

    def fetch_observations(self, trace_id: str) -> list[dict]:
        """Fetch observations for a trace to find error root cause.

        Returns a list of dicts with observation details.
        """
        time.sleep(0.5)  # Rate limit courtesy
        try:
            response = self._client.observations.get_many(
                trace_id=trace_id,
                limit=100,
            )
            results = []
            for obs in response.data:
                results.append(
                    {
                        "id": obs.id,
                        "name": obs.name,
                        "type": obs.type,
                        "level": obs.level.value if obs.level else None,
                        "status_message": obs.status_message,
                        "output": obs.output,
                        "metadata": obs.metadata,
                    }
                )
            logger.info(
                "Trace %s: %d observations, %d with ERROR level",
                trace_id,
                len(results),
                sum(1 for r in results if r["level"] == "ERROR"),
            )
            return results
        except Exception:
            logger.exception("Failed to fetch observations for trace %s", trace_id)
            return []

