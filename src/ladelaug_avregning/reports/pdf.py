"""PDF rendering for settlement reports (decision C9, US-906).

WeasyPrint turns the self-contained HTML report into a PDF. Its wheel is a pure
Python package but it dlopen's Pango / cairo / GObject at import time; on a host
without those system libraries the import raises ``OSError``. We swallow that
here so the app still boots and the HTML reports keep working — the ``.pdf``
endpoints then return ``503 pdf_unavailable``. The failure is logged and the
exception string is kept in ``PDF_IMPORT_ERROR`` (surfaced at
``GET /api/system/health``) so it is never silent.
"""

from __future__ import annotations

import logging

from ladelaug_avregning.errors import DomainError

log = logging.getLogger(__name__)

PDF_IMPORT_ERROR: str | None = None

try:  # pragma: no cover - branch depends on the host's system libraries
    import weasyprint

    PDF_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 - any failure (missing libs, bad build) disables PDF
    weasyprint = None  # type: ignore[assignment]
    PDF_AVAILABLE = False
    PDF_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    log.warning(
        "WeasyPrint unavailable; PDF endpoints will return 503 pdf_unavailable: %s",
        PDF_IMPORT_ERROR,
    )


def html_to_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """Render a full HTML document to PDF bytes.

    Raises :class:`DomainError` (``pdf_unavailable``, 503) when WeasyPrint and
    its native dependencies are not importable on this host.
    """
    if not PDF_AVAILABLE or weasyprint is None:
        raise DomainError(
            "pdf_unavailable",
            "PDF rendering is not available on this server (WeasyPrint could not be loaded).",
            status=503,
        )
    return weasyprint.HTML(string=html, base_url=base_url).write_pdf()
