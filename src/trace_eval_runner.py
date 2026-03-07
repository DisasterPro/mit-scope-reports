"""Entry point for 30-minute trace evaluation cron.

Fetches recent production traces, runs lightweight eval on each,
and writes results to scope-eval-all-runs.md.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analyzers.trace_eval import analyze_trace_evals
from .langfuse_client import LangfuseDataFetcher
from .markdown_writer import write_trace_eval_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Default lookback: 35 min (5-min overlap for cron safety).
# First run (empty output file): 24 hours to backfill.
_DEFAULT_LOOKBACK_MINUTES = 35
_BACKFILL_LOOKBACK_MINUTES = 1440  # 24 hours


def _get_existing_trace_ids(output_path: Path) -> set[str]:
    """Read already-evaluated trace IDs (first 8 chars) from the output file."""
    if not output_path.exists():
        return set()
    text = output_path.read_text(encoding="utf-8")
    return set(re.findall(r"^## ([a-f0-9]{8}) --", text, re.MULTILINE))


def main() -> None:
    """Run trace eval on recent production traces."""
    host = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    eval_llm_key = os.environ.get("EVAL_LLM_API_KEY")

    if not public_key or not secret_key:
        logger.error("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        sys.exit(1)

    # Determine output path early to check existing state
    project_root = Path(__file__).resolve().parent.parent
    docs_dir = project_root / "docs"
    docs_dir.mkdir(exist_ok=True)
    output_path = docs_dir / "scope-eval-all-runs.md"

    existing_ids = _get_existing_trace_ids(output_path)

    # Determine lookback window
    override_minutes = os.environ.get("EVAL_LOOKBACK_MINUTES")
    if override_minutes:
        lookback = int(override_minutes)
    elif not existing_ids:
        lookback = _BACKFILL_LOOKBACK_MINUTES
        logger.info("First run (no existing evals) -- backfilling last %d minutes", lookback)
    else:
        lookback = _DEFAULT_LOOKBACK_MINUTES

    now = datetime.now(timezone.utc)
    from_ts = now - timedelta(minutes=lookback)

    logger.info("Trace eval window: %s to %s (%d min)", from_ts.isoformat(), now.isoformat(), lookback)

    # Fetch traces
    fetcher = LangfuseDataFetcher(host, public_key, secret_key)
    traces = fetcher.fetch_all_production_traces(from_ts, now)

    if not traces:
        logger.info("No traces found in window, nothing to do")
        return

    # Filter out already-evaluated traces
    new_traces = [t for t in traces if t.id[:8] not in existing_ids]
    logger.info(
        "Found %d traces in window, %d already evaluated, %d new",
        len(traces), len(traces) - len(new_traces), len(new_traces),
    )

    if not new_traces:
        logger.info("All traces already evaluated, nothing to do")
        return

    traces = new_traces

    # Set up LLM client if key is available
    llm_client = None
    if eval_llm_key:
        try:
            from openai import AzureOpenAI, OpenAI

            azure_endpoint = os.environ.get("EVAL_LLM_AZURE_ENDPOINT")
            if azure_endpoint:
                llm_client = AzureOpenAI(
                    api_key=eval_llm_key,
                    azure_endpoint=azure_endpoint,
                    api_version=os.environ.get(
                        "EVAL_LLM_API_VERSION", "2024-02-15-preview"
                    ),
                )
            else:
                llm_client = OpenAI(api_key=eval_llm_key)
            logger.info("LLM client initialized for narrative generation")
        except ImportError:
            logger.warning("openai package not installed, using template fallback")
    else:
        logger.info("EVAL_LLM_API_KEY not set, using template fallback for narrative")

    # Run evaluations
    reports = analyze_trace_evals(traces, fetcher, llm_client)

    if not reports:
        logger.info("No reports generated")
        return

    # Write results
    write_trace_eval_report(output_path, reports)
    logger.info("Done! Evaluated %d traces", len(reports))


if __name__ == "__main__":
    main()
