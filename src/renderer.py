"""HTML report renderer using Jinja2."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import CostReport, ErrorReport, SalesReport, UsageReport


def render_report(
    usage: UsageReport,
    costs: CostReport,
    errors: ErrorReport,
    sales: SalesReport | None,
    generated_at: datetime,
    template_dir: str | Path = "templates",
    period: str = "weekly",
) -> str:
    """Render the combined report as interactive HTML."""
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=True,
    )
    template = env.get_template("report.html.j2")
    return template.render(
        usage=usage,
        costs=costs,
        errors=errors,
        sales=sales,
        generated_at=generated_at,
        period=period,
    )
