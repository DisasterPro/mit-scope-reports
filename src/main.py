"""Entry point for MitScope report generation (daily and weekly).

Fetches production trace data from Langfuse, runs usage/cost/error
analytics, renders an interactive HTML report, and optionally posts
a summary to Slack.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analyzers import analyze_costs, analyze_errors, analyze_usage
from .analyzers.trace_eval import analyze_trace_evals
from .index_builder import build_index_page
from .langfuse_client import LangfuseDataFetcher
from .markdown_writer import write_markdown_reports, write_trace_eval_report
from .renderer import render_report
from .slack import post_to_slack

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Generate a daily or weekly report based on REPORT_PERIOD env var."""
    # 1. Configuration from environment
    host = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    report_base_url = os.environ.get(
        "REPORT_BASE_URL", "https://disasterpro.github.io/mit-scope-reports"
    )
    period = os.environ.get("REPORT_PERIOD", "daily").lower()

    if period not in ("daily", "weekly"):
        logger.error("REPORT_PERIOD must be 'daily' or 'weekly', got '%s'", period)
        sys.exit(1)

    if not public_key or not secret_key:
        logger.error("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        sys.exit(1)

    is_weekly = period == "weekly"
    days = 7 if is_weekly else 1

    # 2. Calculate time window
    now = datetime.now(timezone.utc)
    to_ts = now
    from_ts = to_ts - timedelta(days=days)

    logger.info(
        "%s report period: %s to %s",
        period.capitalize(),
        from_ts.isoformat(),
        to_ts.isoformat(),
    )

    # 3. Fetch traces
    fetcher = LangfuseDataFetcher(host, public_key, secret_key)
    traces = fetcher.fetch_all_production_traces(from_ts, to_ts)

    if not traces:
        logger.warning("No production traces found for the period")

    logger.info("Fetched %d production traces", len(traces))

    # 4. Run analyzers
    logger.info("Running usage analysis...")
    usage = analyze_usage(traces, from_ts, to_ts)

    logger.info("Running cost analysis...")
    costs = analyze_costs(traces)

    logger.info("Running error analysis...")
    errors = analyze_errors(traces, fetcher)

    # 4b. Run trace evaluations (lightweight per-trace evals)
    logger.info("Running trace evaluations...")
    llm_client = None
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic
            llm_client = anthropic.Anthropic(api_key=anthropic_key)
        except ImportError:
            logger.warning("anthropic package not installed, skipping LLM narratives")
    else:
        logger.info("ANTHROPIC_API_KEY not set, using template-based narratives")

    trace_evals = analyze_trace_evals(traces, fetcher, llm_client)
    logger.info("Evaluated %d traces", len(trace_evals))

    # 5. Render HTML
    logger.info("Rendering HTML report...")
    project_root = Path(__file__).resolve().parent.parent
    template_dir = project_root / "templates"
    html = render_report(usage, costs, errors, now, template_dir, period=period)

    # 6. Write output files
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)

    # Latest report (overwrites index.html — always the most recent run)
    index_path = reports_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", index_path)

    # Archive with date and period type
    archive_dir = reports_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    date_str = from_ts.strftime("%Y-%m-%d")
    archive_name = f"{date_str}-{period}.html"
    archive_path = archive_dir / archive_name
    archive_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", archive_path)

    # Build the archive index page (lists all reports chronologically)
    build_index_page(archive_dir, reports_dir / "history.html")

    # 7. Update markdown report docs
    logger.info("Updating markdown reports...")
    docs_dir = project_root / "docs"
    write_markdown_reports(docs_dir, usage, costs, errors, now, period)

    # 7b. Write trace evaluation report
    if trace_evals:
        eval_report_path = docs_dir / "scope-eval-all-runs.md"
        write_trace_eval_report(eval_report_path, trace_evals)
        logger.info("Wrote trace eval report to %s", eval_report_path)

    # 8. Post to Slack (if configured)
    if slack_webhook_url:
        logger.info("Posting to Slack...")
        post_to_slack(
            webhook_url=slack_webhook_url,
            report_url=report_base_url,
            period_start=from_ts,
            period_end=to_ts,
            usage=usage,
            errors=errors,
            period=period,
        )
    else:
        logger.info("SLACK_WEBHOOK_URL not set, skipping notification")

    logger.info(
        "Done! %s report covers %d scopes.", period.capitalize(), usage.total_scopes
    )


if __name__ == "__main__":
    main()
