"""HTML report renderer using Jinja2."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import CostReport, ErrorReport, UsageReport


def render_report(
    usage: UsageReport,
    costs: CostReport,
    errors: ErrorReport,
    generated_at: datetime,
    template_dir: str | Path = "templates",
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
        generated_at=generated_at,
    )
