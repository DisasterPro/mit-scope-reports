"""Parse scope-eval-all-runs.md and build Sales report hierarchy.

Reads the enhanced eval data, filters by date range, excludes internal
users, applies outreach trigger flags, and groups by org → user → traces.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from html import escape

from .models import SalesOrg, SalesReport, SalesTrace, SalesUser
from .org_resolver import resolve_org

logger = logging.getLogger(__name__)

# Internal domains excluded from sales reports
EXCLUDED_DOMAINS = {"encircleapp.com"}


def fetch_github_file(repo: str, path: str, token: str, ref: str = "main") -> str | None:
    """Fetch a file from GitHub API and return its decoded content."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return base64.b64decode(data["content"]).decode("utf-8")
    except Exception:
        logger.exception("Failed to fetch %s from %s", path, repo)
        return None


class SalesDataBuilder:
    """Parse scope-eval-all-runs.md and build a SalesReport."""

    def build(
        self, eval_content: str, from_ts: datetime, to_ts: datetime
    ) -> SalesReport:
        """Parse, filter, flag, and group traces into a SalesReport."""
        traces = self._parse_index_table(eval_content)
        traces = self._filter_date_range(traces, from_ts, to_ts)
        traces = self._exclude_internal(traces)
        traces = self._apply_flags(traces, eval_content)
        traces = self._extract_narratives(traces, eval_content)
        orgs = self._group_by_org_and_user(traces)

        total_flagged = sum(1 for t in traces if t.flags)
        unique_users = set(t.user_email for t in traces)

        return SalesReport(
            period_start=from_ts,
            period_end=to_ts,
            total_traces=len(traces),
            total_flagged=total_flagged,
            total_orgs=len(orgs),
            total_users=len(unique_users),
            orgs=orgs,
        )

    def _parse_index_table(self, content: str) -> list[SalesTrace]:
        """Parse the index table from scope-eval-all-runs.md."""
        traces: list[SalesTrace] = []
        in_table = False
        header_seen = False

        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|"):
                if in_table and header_seen:
                    break
                continue

            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not cells or len(cells) < 13:
                continue

            # Detect header row
            if cells[0] == "Trace" or "---" in cells[0]:
                in_table = True
                if cells[0] == "Trace":
                    header_seen = True
                continue

            if not header_seen:
                continue

            try:
                trace_id = cells[0].strip()
                version = cells[1].strip()
                date = cells[2].strip()
                user = cells[3].strip()
                time_val = cells[4].strip()
                input_score = cells[5].strip()
                pipeline_score = cells[6].strip()
                issue_score = cells[7].strip()
                overall_score = cells[8].strip()
                rooms = cells[9].strip()
                photos_str = cells[10].strip()
                notes_str = cells[11].strip()
                plans_str = cells[12].strip()

                # Parse numeric overall score
                overall_match = re.match(r"([\d.]+)", overall_score)
                overall_numeric = float(overall_match.group(1)) if overall_match else 0.0

                # Parse numeric counts
                photos = int(re.sub(r"[^\d]", "", photos_str) or "0")
                notes = int(re.sub(r"[^\d]", "", notes_str) or "0")
                plans = int(re.sub(r"[^\d]", "", plans_str) or "0")

                traces.append(
                    SalesTrace(
                        trace_id=trace_id,
                        date=date,
                        version=version,
                        user_email=user,
                        time=time_val,
                        input_score=input_score,
                        pipeline_score=pipeline_score,
                        issue_score=issue_score,
                        overall_score=overall_score,
                        overall_numeric=overall_numeric,
                        rooms=rooms,
                        photos=photos,
                        notes=notes,
                        plans=plans,
                    )
                )
            except (ValueError, IndexError):
                continue

        logger.info("Parsed %d traces from eval index table", len(traces))
        return traces

    def _filter_date_range(
        self, traces: list[SalesTrace], from_ts: datetime, to_ts: datetime
    ) -> list[SalesTrace]:
        """Filter traces to the target date range."""
        from_date = from_ts.strftime("%Y-%m-%d")
        to_date = to_ts.strftime("%Y-%m-%d")
        filtered = [t for t in traces if from_date <= t.date < to_date]
        logger.info("Date filter: %d -> %d traces (%s to %s)", len(traces), len(filtered), from_date, to_date)
        return filtered

    def _exclude_internal(self, traces: list[SalesTrace]) -> list[SalesTrace]:
        """Exclude internal test users."""
        filtered = []
        for t in traces:
            domain = t.user_email.rsplit("@", 1)[-1].lower() if t.user_email else ""
            if domain not in EXCLUDED_DOMAINS:
                filtered.append(t)
        excluded = len(traces) - len(filtered)
        if excluded:
            logger.info("Excluded %d internal traces", excluded)
        return filtered

    def _apply_flags(
        self, traces: list[SalesTrace], content: str
    ) -> list[SalesTrace]:
        """Apply outreach trigger flags to each trace."""
        for trace in traces:
            flags: list[str] = []

            # Low overall score
            if trace.overall_numeric <= 2.7:
                flags.append("LOW SCORE")

            # Pipeline failure
            pipeline_match = re.match(r"(\d)", trace.pipeline_score)
            if pipeline_match and int(pipeline_match.group(1)) <= 2:
                flags.append("PIPELINE")

            # Zero-data scope
            input_match = re.match(r"(\d)", trace.input_score)
            if input_match and int(input_match.group(1)) <= 1:
                if trace.photos == 0 or trace.notes == 0:
                    flags.append("NO DATA")

            # Check trace detail section for flag signals
            trace_section = self._get_trace_section(content, trace.trace_id)
            if trace_section:
                # Floor plan issues: room names don't match floor plan labels
                provided = self._extract_after(trace_section, "### What Was Provided")
                if provided and re.search(r"Room Name Matching\s*\|\s*Issues", provided):
                    flags.append("FLOOR PLAN")

                trace.is_enhanced = "### Bug Assessment" in trace_section

                if trace.is_enhanced:
                    bug_table = self._extract_after(trace_section, "### Bug Assessment")

                    # hallucination FAIL with fabricated/orphaned
                    hall_match = re.search(
                        r"hallucination.*\*\*FAIL\*\*.*?(fabricat|orphan)",
                        bug_table, re.IGNORECASE,
                    )
                    if hall_match:
                        flags.append("ORG ROOMS")

                    # Count bugs
                    bug_count = len(re.findall(r"\*\*FAIL\*\*", bug_table))
                    if bug_count:
                        trace.bug_summary = f"{bug_count} bug{'s' if bug_count != 1 else ''} found"

            trace.flags = flags

        flagged = sum(1 for t in traces if t.flags)
        logger.info("Flagged %d of %d traces for outreach", flagged, len(traces))
        return traces

    def _extract_narratives(
        self, traces: list[SalesTrace], content: str
    ) -> list[SalesTrace]:
        """Extract narrative HTML for all traces (not just enhanced)."""
        for trace in traces:
            section = self._get_trace_section(content, trace.trace_id)
            if not section:
                continue

            html_parts: list[str] = []

            # Trace ID header
            html_parts.append(
                f'<h4 style="font-family:monospace;font-size:.78rem;color:var(--txt3)">'
                f'Langfuse Trace: {escape(trace.trace_id)}</h4>'
            )

            # 1. What Was Provided table
            provided_section = self._extract_after(section, "### What Was Provided")
            if provided_section:
                html_parts.append(self._markdown_table_to_html(provided_section, "What Was Provided"))

            # 2. Input Assessment
            input_text = self._extract_after(section, "### Input Assessment")
            if input_text:
                html_parts.append(f"<h4>Input Assessment</h4><p>{escape(input_text.strip())}</p>")

            # 3. Issue Assessment
            issue_text = self._extract_after(section, "### Issue Assessment")
            if issue_text:
                html_parts.append(f"<h4>Issue Assessment</h4><p>{escape(issue_text.strip())}</p>")

            # 4. Recommendations
            rec_section = self._extract_after(section, "### Recommendations")
            if rec_section:
                html_parts.append(self._recommendations_to_html(rec_section))

            # 5. Pipeline Assessment
            pipeline_text = self._extract_after(section, "### Pipeline Assessment")
            if pipeline_text:
                html_parts.append(f"<h4>Pipeline Assessment</h4><p>{escape(pipeline_text.strip())}</p>")

            trace.narrative_html = "\n".join(html_parts)

        return traces

    def _group_by_org_and_user(self, traces: list[SalesTrace]) -> list[SalesOrg]:
        """Group traces into org → user hierarchy."""
        org_map: dict[str, dict[str, list[SalesTrace]]] = defaultdict(lambda: defaultdict(list))

        for trace in traces:
            org_name = resolve_org(trace.user_email) if trace.user_email else "unknown"
            org_map[org_name][trace.user_email].append(trace)

        orgs: list[SalesOrg] = []
        for org_name in sorted(org_map.keys()):
            users_map = org_map[org_name]
            users: list[SalesUser] = []

            for email in sorted(users_map.keys()):
                user_traces = sorted(users_map[email], key=lambda t: t.date, reverse=True)
                flagged = sum(1 for t in user_traces if t.flags)
                users.append(
                    SalesUser(
                        email=email,
                        trace_count=len(user_traces),
                        flagged_count=flagged,
                        traces=user_traces,
                    )
                )

            org_traces = sum(u.trace_count for u in users)
            org_flagged = sum(u.flagged_count for u in users)
            orgs.append(
                SalesOrg(
                    name=org_name,
                    user_count=len(users),
                    trace_count=org_traces,
                    flagged_count=org_flagged,
                    users=users,
                )
            )

        return orgs

    # ── Helpers ──

    @staticmethod
    def _room_count(rooms_str: str) -> int:
        """Extract total room count from e.g. '38 (38/0)'."""
        m = re.match(r"(\d+)", rooms_str)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _get_trace_section(content: str, trace_id: str) -> str | None:
        """Extract the full section for a trace ID from the eval file."""
        pattern = rf"## {re.escape(trace_id[:32])}"
        match = re.search(pattern, content)
        if not match:
            return None

        start = match.start()
        next_section = re.search(r"\n## [0-9a-f]", content[start + 1:])
        end = start + 1 + next_section.start() if next_section else len(content)
        return content[start:end]

    @staticmethod
    def _extract_after(section: str, header: str) -> str:
        """Extract text after a markdown header until the next header."""
        idx = section.find(header)
        if idx == -1:
            return ""
        start = idx + len(header)
        next_header = re.search(r"\n### ", section[start:])
        end = start + next_header.start() if next_header else len(section)
        return section[start:end].strip()

    @staticmethod
    def _markdown_table_to_html(md_table: str, title: str) -> str:
        """Convert a markdown table to simple HTML."""
        lines = [l.strip() for l in md_table.split("\n") if l.strip().startswith("|")]
        if len(lines) < 2:
            return ""

        html = f'<h4>{escape(title)}</h4><table><thead><tr>'
        headers = [c.strip() for c in lines[0].split("|")[1:-1]]
        for h in headers:
            html += f"<th>{escape(h)}</th>"
        html += "</tr></thead><tbody>"

        for line in lines[2:]:  # Skip header + separator
            cells = [c.strip() for c in line.split("|")[1:-1]]
            html += "<tr>"
            for cell in cells:
                # Convert **FAIL** to badge
                cell_html = escape(cell)
                cell_html = cell_html.replace("**FAIL**", '<span class="badge badge-s">FAIL</span>')
                cell_html = cell_html.replace("PASS", '<span class="badge badge-ok">PASS</span>')
                html += f"<td>{cell_html}</td>"
            html += "</tr>"

        html += "</tbody></table>"
        return html

    @staticmethod
    def _recommendations_to_html(md_recs: str) -> str:
        """Convert markdown recommendations to HTML list."""
        items = re.findall(r"\d+\.\s+\*\*(.*?)\*\*\.?\s*(.*?)(?=\n\d+\.|\Z)", md_recs, re.DOTALL)
        if not items:
            return ""

        html = "<h4>Recommendations</h4><ol>"
        for title, body in items:
            html += f"<li><strong>{escape(title)}.</strong> {escape(body.strip())}</li>"
        html += "</ol>"
        return html
