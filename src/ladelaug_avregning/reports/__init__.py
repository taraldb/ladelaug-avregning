"""Settlement report rendering (US-905, US-904/906 member-facing).

Self-contained HTML — one page per member plus a settlement summary — plus
optional PDF rendering via WeasyPrint (``pdf.html_to_pdf``, decision C9). The
forecast / recommended-top-up section of the member report is filled in when a
forecast dict is supplied (decision C10).
"""

from ladelaug_avregning.reports.pdf import PDF_AVAILABLE, html_to_pdf
from ladelaug_avregning.reports.settlement_report import (
    render_member_report,
    render_summary_report,
    write_reports,
)

__all__ = [
    "PDF_AVAILABLE",
    "html_to_pdf",
    "render_member_report",
    "render_summary_report",
    "write_reports",
]
