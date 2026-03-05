"""Slack notification via incoming webhook."""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime

from .models import ErrorReport, UsageReport

logger = logging.getLogger(__name__)


def post_to_slack(
    webhook_url: str,
    report_url: str,
    period_start: datetime,
    period_end: datetime,
    usage: UsageReport,
    errors: ErrorReport,
    period: str = "weekly",
) -> None:
    """Post a summary notification to Slack with a link to the full report."""
    period_str = f"{period_start:%Y-%m-%d} to {period_end:%Y-%m-%d}"
    label = "Weekly" if period == "weekly" else "Daily"

    payload = {
        "text": f"{label} Mitigation Scope Report ({period_str})",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{label} Mitigation Scope Report",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Period:*\n{period_str}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Scopes:*\n{usage.total_scopes:,}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Organizations:*\n{usage.unique_orgs}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Total Cost:*\n${usage.total_cost:.2f}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Avg Cost:*\n${usage.avg_cost:.2f}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Error Rate:*\n{errors.error_rate:.1f}%",
                    },
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Full Report",
                        },
                        "url": report_url,
                        "style": "primary",
                    }
                ],
            },
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("Slack notification sent successfully")
            else:
                logger.warning("Slack returned status %d", resp.status)
    except Exception:
        logger.exception("Failed to send Slack notification")
