"""Build an HTML index page listing all archived reports."""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Matches filenames like 2026-03-04-daily.html or 2026-03-01-weekly.html
_REPORT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(daily|weekly)\.html$")


def build_index_page(archive_dir: Path, output_path: Path) -> None:
    """Scan archive_dir for report files and write an HTML index page.

    Reports are listed in reverse chronological order.  Daily reports are
    grouped together, with weekly reports visually separated so the
    pattern looks like:
        daily Mar 4 | daily Mar 3 | daily Mar 2 | ... | WEEKLY Feb 24-Mar 2
        daily Mar 11 | daily Mar 10 | ... | WEEKLY Mar 2-Mar 9
    """
    entries: list[tuple[str, str, str]] = []  # (date_str, period, filename)

    for p in archive_dir.iterdir():
        m = _REPORT_RE.match(p.name)
        if m:
            entries.append((m.group(1), m.group(2), p.name))

    # Also pick up old-format archives (YYYY-MM-DD.html without period suffix)
    for p in archive_dir.iterdir():
        if re.match(r"^\d{4}-\d{2}-\d{2}\.html$", p.name):
            date_str = p.name.replace(".html", "")
            entries.append((date_str, "weekly", p.name))

    # Sort reverse chronological, weekly reports sort after daily on same date
    entries.sort(key=lambda e: (e[0], 0 if e[1] == "weekly" else 1), reverse=True)

    rows = []
    for date_str, period, filename in entries:
        label = "Weekly" if period == "weekly" else "Daily"
        badge_cls = "badge-weekly" if period == "weekly" else "badge-daily"
        rows.append(
            f'<tr class="row-{period}">'
            f'<td><span class="badge {badge_cls}">{label}</span></td>'
            f"<td>{date_str}</td>"
            f'<td><a href="archive/{filename}">View Report</a></td>'
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MitScope Report History</title>
<style>
:root{{--enc:#f26522;--txt:#1e293b;--txt2:#475569;--bg:#f4f5f7;--card:#fff;--bdr:#e2e8f0}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--txt);line-height:1.5}}
.hdr{{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;padding:1.25rem 2rem;display:flex;align-items:center;gap:1rem}}
.hdr h1{{font-size:1.3rem;font-weight:700}}
.hdr .pill{{background:var(--enc);padding:.2rem .7rem;border-radius:20px;font-size:.75rem;font-weight:600}}
.container{{max-width:800px;margin:2rem auto;padding:0 1rem}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
th{{background:#f8fafc;padding:.6rem 1rem;text-align:left;font-size:.8rem;font-weight:600;color:var(--txt2);border-bottom:2px solid var(--bdr)}}
td{{padding:.5rem 1rem;border-bottom:1px solid var(--bdr);font-size:.85rem}}
tr:hover td{{background:#fafbfc}}
a{{color:var(--enc);text-decoration:none;font-weight:600}}
a:hover{{text-decoration:underline}}
.badge{{display:inline-block;padding:.15rem .5rem;border-radius:12px;font-size:.7rem;font-weight:600}}
.badge-weekly{{background:#eff6ff;color:#2563eb}}
.badge-daily{{background:#f0fdf4;color:#16a34a}}
.row-weekly td{{background:#f8fafc}}
.back{{display:inline-block;margin-bottom:1rem;color:var(--enc);font-weight:600;text-decoration:none;font-size:.85rem}}
.back:hover{{text-decoration:underline}}
.ft{{text-align:center;padding:1.5rem;font-size:.72rem;color:var(--txt2)}}
</style>
</head>
<body>
<div class="hdr">
<h1>MitScope Report History</h1>
<span class="pill">ARCHIVE</span>
</div>
<div class="container">
<a class="back" href="index.html">&larr; Latest Report</a>
<table>
<thead><tr><th>Type</th><th>Date</th><th>Report</th></tr></thead>
<tbody>
{"".join(rows) if rows else '<tr><td colspan="3" style="text-align:center;color:var(--txt2);padding:2rem">No archived reports yet.</td></tr>'}
</tbody>
</table>
</div>
<div class="ft">MitScope Production Report &mdash; Encircle</div>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    logger.info("Wrote report index: %s (%d entries)", output_path, len(entries))
