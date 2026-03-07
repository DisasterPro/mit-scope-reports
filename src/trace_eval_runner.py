"""Entry point for 30-minute trace evaluation cron.

Fetches recent production traces, runs lightweight eval on each,
and writes results to scope-eval-all-runs.md.
"""

from __future__ import annotations

import logging
import os
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


def main() -> None:
    """Run trace eval on recent production traces."""
    host = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    eval_llm_key = os.environ.get("EVAL_LLM_API_KEY")

    if not public_key or not secret_key:
        logger.error("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        sys.exit(1)

    # Time window: last 35 minutes (5-min overlap for safety)
    now = datetime.now(timezone.utc)
    from_ts = now - timedelta(minutes=35)

    logger.info("Trace eval window: %s to %s", from_ts.isoformat(), now.isoformat())

    # Fetch traces
    fetcher = LangfuseDataFetcher(host, public_key, secret_key)
    traces = fetcher.fetch_all_production_traces(from_ts, now)

    if not traces:
        logger.info("No new traces in window, nothing to do")
        return

    logger.info("Found %d traces to evaluate", len(traces))

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
    project_root = Path(__file__).resolve().parent.parent
    docs_dir = project_root / "docs"
    docs_dir.mkdir(exist_ok=True)
    output_path = docs_dir / "scope-eval-all-runs.md"

    write_trace_eval_report(output_path, reports)
    logger.info("Done! Evaluated %d traces", len(reports))


if __name__ == "__main__":
    main()
