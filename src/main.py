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
from .sales_parser import SalesDataBuilder, fetch_github_file
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

    phase = os.environ.get("REPORT_PHASE", "full").lower()

    if period not in ("daily", "weekly"):
        logger.error("REPORT_PERIOD must be 'daily' or 'weekly', got '%s'", period)
        sys.exit(1)

    if phase not in ("full", "reports-only", "sales-only"):
        logger.error("REPORT_PHASE must be 'full', 'reports-only', or 'sales-only', got '%s'", phase)
        sys.exit(1)

    if not public_key or not secret_key:
        logger.error("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        sys.exit(1)

    is_weekly = period == "weekly"

    # 2. Calculate time window — exact UTC calendar day boundaries
    now_utc = datetime.now(timezone.utc)
    if is_weekly:
        end_date = now_utc.date() - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
    else:
        end_date = now_utc.date() - timedelta(days=1)
        start_date = end_date

    from_ts = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    to_ts = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

    logger.info(
        "%s report period: %s to %s",
        period.capitalize(),
        from_ts.isoformat(),
        to_ts.isoformat(),
    )

    project_root = Path(__file__).resolve().parent.parent
    template_dir = project_root / "templates"
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)
    docs_dir = project_root / "docs"

    usage = None
    costs = None
    errors = None
    trace_evals = []
    sales = None

    # 3. Fetch traces and run analyzers (skip for sales-only phase)
    if phase in ("full", "reports-only"):
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

        # 7. Update markdown report docs
        logger.info("Updating markdown reports...")
        write_markdown_reports(docs_dir, usage, costs, errors, now_utc, period)

        # 7b. Write trace evaluation report
        if trace_evals:
            eval_report_path = docs_dir / "scope-eval-all-runs.md"
            write_trace_eval_report(eval_report_path, trace_evals)
            logger.info("Wrote trace eval report to %s", eval_report_path)

    # 4c. Build Sales data (for sales-only or full phase)
    if phase in ("full", "sales-only"):
        eval_content = None

        # Try local docs file first (available during full phase after trace evals)
        local_eval_path = docs_dir / "scope-eval-all-runs.md"
        if local_eval_path.exists():
            logger.info("Reading local %s for Sales page...", local_eval_path)
            eval_content = local_eval_path.read_text(encoding="utf-8")

        # Fall back to fetching from GitHub (for sales-only phase or if local missing)
        if not eval_content:
            gh_token = os.environ.get("GH_TOKEN") or os.environ.get("AI_SERVICES_PAT")
            if gh_token:
                logger.info("Fetching scope-eval-all-runs.md from GitHub for Sales page...")
                eval_content = fetch_github_file(
                    repo="EncircleInc/ai-services",
                    path="services/mitigation-scope/joe/evals/traces/2_scope-eval-all-runs.md",
                    token=gh_token,
                    ref="MitScopeV29.3",
                )
                # Fall back to docs path in same repo
                if not eval_content:
                    eval_content = fetch_github_file(
                        repo="DisasterPro/mit-scope-reports",
                        path="docs/scope-eval-all-runs.md",
                        token=gh_token,
                    )
            else:
                logger.warning("GH_TOKEN/AI_SERVICES_PAT not set")

        if eval_content:
            builder = SalesDataBuilder()
            sales = builder.build(eval_content, from_ts, to_ts)
            logger.info("Sales data: %d traces, %d flagged", sales.total_traces, sales.total_flagged)
        else:
            logger.warning("No eval data available, skipping Sales page")

    # 5. Render HTML (always — use whatever data we have)
    logger.info("Rendering HTML report...")

    # For sales-only phase, load existing report data if available
    if phase == "sales-only" and usage is None:
        # Re-read existing markdown reports to reconstruct minimal data for the 3-tab render
        # The HTML will show stale data for other tabs but fresh Sales data
        fetcher = LangfuseDataFetcher(host, public_key, secret_key)
        traces = fetcher.fetch_all_production_traces(from_ts, to_ts)
        logger.info("Fetched %d traces for HTML rendering", len(traces))
        usage = analyze_usage(traces, from_ts, to_ts)
        costs = analyze_costs(traces)
        errors = analyze_errors(traces, fetcher)

    html = render_report(usage, costs, errors, sales, now_utc, template_dir, period=period)

    # 6. Write output files
    index_path = reports_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", index_path)

    archive_dir = reports_dir / "archive"
    archive_dir.mkdir(exist_ok=True)
    date_str = from_ts.strftime("%Y-%m-%d")
    archive_name = f"{date_str}-{period}.html"
    archive_path = archive_dir / archive_name
    archive_path.write_text(html, encoding="utf-8")
    logger.info("Wrote %s", archive_path)

    build_index_page(archive_dir, reports_dir / "history.html")

    # 8. Post to Slack (if configured, skip for sales-only)
    if slack_webhook_url and phase != "sales-only":
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
        logger.info("Slack notification skipped")

    logger.info(
        "Done! %s report (%s phase) covers %d scopes.",
        period.capitalize(), phase, usage.total_scopes if usage else 0,
    )


if __name__ == "__main__":
    main()

