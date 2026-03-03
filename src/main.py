"""Entry point for weekly MitScope report generation.

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
from .langfuse_client import LangfuseDataFetcher
from .renderer import render_report
from .slack import post_to_slack

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Generate the weekly report."""
    # 1. Configuration from environment
    host = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    slack_webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    report_base_url = os.environ.get(
        "REPORT_BASE_URL", "https://disasterpro.github.io/mit-scope-reports"
    )

    if not public_key or not secret_key:
        logger.error("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        sys.exit(1)

    # 2. Calculate 7-day window
    now = datetime.now(timezone.utc)
    to_ts = now
    from_ts = to_ts - timedelta(days=7)

    logger.info("Report period: %s to %s", from_ts.isoformat(), to_ts.isoformat())

    # 3. Fetch traces
    fetcher = LangfuseDataFetcher(host, public_key, secret_key)
    traces = fetcher.fetch_all_production_traces(from_ts, to_ts)

    if not traces:
        logger.warning("No production traces found for the period")
        # Still generate a report with zeros
        pass

    logger.info("Fetched %d production traces", len(traces))

    # 4. Run analyzers
    logger.info("Running usage analysis...")
    usage = analyze_usage(traces, from_ts, to_ts)

    logger.info("Running cost analysis...")
    costs = analyze_costs(traces)

    logger.info("Running error analysis...")
    errors = analyze_errors(traces, fetcher)

    # 5. Render HTML
    logger.info("Rendering HTML report...")
    # Resolve template directory relative to the project root
    project_root = Path(__file__).resolve().parent.parent
    template_dir = project_root / "templates"
    html = render_report(usage, costs, errors, now, template_dir)

    # 6. Write output files
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)

    # Latest report (overwrites)
    index_path = reports_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", index_path)

    # Archive with date
    archive_dir = reports_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    archive_name = from_ts.strftime("%Y-%m-%d") + ".html"
    archive_path = archive_dir / archive_name
    archive_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", archive_path)

    # 7. Post to Slack (if configured)
    if slack_webhook_url:
        logger.info("Posting to Slack...")
        post_to_slack(
            webhook_url=slack_webhook_url,
            report_url=report_base_url,
            period_start=from_ts,
            period_end=to_ts,
            usage=usage,
            errors=errors,
        )
    else:
        logger.info("SLACK_WEBHOOK_URL not set, skipping notification")

    logger.info("Done! Report covers %d scopes.", usage.total_scopes)


if __name__ == "__main__":
    main()
