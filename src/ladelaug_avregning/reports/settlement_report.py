"""HTML settlement reports.

``render_member_report`` / ``render_summary_report`` are pure functions over the
``SettlementRepo.compute`` result; ``write_reports`` persists them under
``state/reports/<period>/`` at post time.
"""

from __future__ import annotations

import contextlib
import html
from decimal import Decimal
from pathlib import Path
from typing import Any

from ladelaug_avregning.money import ore_to_nok

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #1a1a1a; background: #fff; margin: 0; padding: 2rem; }
.wrap { max-width: 720px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.75rem 0 .5rem; border-bottom: 1px solid #e2e2e2;
     padding-bottom: .25rem; }
.muted { color: #666; }
table { width: 100%; border-collapse: collapse; margin: .5rem 0; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #ededed; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.total td, .total td { font-weight: 600; border-top: 2px solid #ccc; border-bottom: none; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: .2rem 1.5rem; }
.kv dt { color: #666; } .kv dd { margin: 0; font-variant-numeric: tabular-nums; }
.neg { color: #b00020; }
footer { margin-top: 2.5rem; font-size: .85rem; color: #888; }
"""


def _esc(v: Any) -> str:
    return html.escape(str(v))


def _nok(value: str | int) -> str:
    """Format a NOK decimal string as ``1 234,56 kr`` (nb-NO)."""
    s = str(value)
    neg = s.startswith("-")
    s = s.lstrip("-")
    whole, _, frac = s.partition(".")
    frac = (frac + "00")[:2]
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return ("-" if neg else "") + " ".join(groups) + f",{frac} kr"


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="nb"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f'<body><div class="wrap">{body}</div></body></html>'
    )


def _forecast_section(forecast: dict[str, Any] | None) -> str:
    """The "Prognose neste måned" / "Anbefalt saldo" block (decision C10).

    ``forecast`` is a :meth:`ForecastRepo.member_forecast` dict. When it is
    ``None`` or ``available`` is false we fall back to a short neutral footer —
    no placeholder promise.
    """
    if not forecast or not forecast.get("available"):
        return (
            "<footer>Prognose for neste måned er ikke tilgjengelig ennå "
            "(for lite avregningshistorikk).</footer>"
        )

    kwh = Decimal(str(forecast["forecast_kwh"])).quantize(Decimal("0.01"))
    monthly_cost = ore_to_nok(int(forecast["forecast_monthly_cost_ore"]))
    recommended_minimum = ore_to_nok(int(forecast["recommended_minimum_ore"]))
    topup_ore = max(0, int(forecast["recommended_minimum_ore"]) - int(forecast["balance_ore"]))
    topup = ore_to_nok(topup_ore)
    return (
        "<h2>Prognose neste måned</h2>"
        '<dl class="kv">'
        f"<dt>Forventet forbruk</dt><dd>{_esc(kwh)} kWh</dd>"
        f"<dt>Estimert månedskostnad</dt><dd>{_nok(str(monthly_cost))}</dd>"
        "</dl>"
        "<h2>Anbefalt saldo / innbetaling</h2>"
        '<dl class="kv">'
        f"<dt>Anbefalt saldo</dt><dd>{_nok(str(recommended_minimum))}</dd>"
        "<dt>Anbefalt innbetaling for å nå anbefalt saldo</dt>"
        f"<dd>{_nok(str(topup))}</dd>"
        "</dl>"
        "<footer>Prognosen er et estimat basert på de siste avregningene og "
        "kan endre seg.</footer>"
    )


def render_member_report(
    result: dict[str, Any],
    member: dict[str, Any],
    forecast: dict[str, Any] | None = None,
) -> str:
    month = _esc(result["period_month"])
    name = _esc(member["full_name"])
    ref = _esc(member["member_reference"])
    lines_rows = (
        "".join(
            f"<tr><td>{_esc(ln['description'])}</td>"
            f'<td class="muted">{"Likt" if ln["kind"] == "equal" else "Forbruk"}</td>'
            f'<td class="num">{_nok(ln["amount_nok"])}</td></tr>'
            for ln in member["lines"]
        )
        or '<tr><td colspan="3" class="muted">Ingen kostnader denne måneden.</td></tr>'
    )

    after_cls = ' class="neg"' if member["balance_after_ore"] < 0 else ""
    body = (
        f"<h1>Avregning {month}</h1>"
        f'<p class="muted">{name} &middot; {ref}</p>'
        "<h2>Forbruk</h2>"
        '<dl class="kv">'
        f"<dt>Ladet energi</dt><dd>{_esc(member['consumption_kwh'])} kWh</dd>"
        f"<dt>Antall ladeøkter</dt><dd>{_esc(member['session_count'])}</dd>"
        "</dl>"
        "<h2>Kostnadsfordeling</h2>"
        '<table><thead><tr><th>Post</th><th>Type</th><th class="num">Din andel</th>'
        "</tr></thead><tbody>"
        f"{lines_rows}"
        f'<tr class="total"><td colspan="2">Sum belastet</td>'
        f'<td class="num">{_nok(member["charge_nok"])}</td></tr>'
        "</tbody></table>"
        "<h2>Saldo</h2>"
        '<dl class="kv">'
        f"<dt>Saldo før avregning</dt><dd>{_nok(member['balance_before_nok'])}</dd>"
        f"<dt>Belastet</dt><dd>-{_nok(member['charge_nok'])}</dd>"
        f"<dt>Saldo etter avregning</dt><dd{after_cls}>{_nok(member['balance_after_nok'])}</dd>"
        "</dl>"
        f"{_forecast_section(forecast)}"
    )
    return _page(f"Avregning {result['period_month']} – {member['full_name']}", body)


def render_summary_report(result: dict[str, Any]) -> str:
    month = _esc(result["period_month"])
    rows = "".join(
        f"<tr><td>{_esc(m['member_reference'])} {_esc(m['full_name'])}</td>"
        f'<td class="num">{_esc(m["consumption_kwh"])}</td>'
        f'<td class="num">{_nok(m["charge_nok"])}</td>'
        f'<td class="num{" neg" if m["balance_after_ore"] < 0 else ""}">'
        f"{_nok(m['balance_after_nok'])}</td></tr>"
        for m in result["members"]
    )
    warn = ""
    if result["warnings"]:
        codes = ", ".join(_esc(w["code"]) for w in result["warnings"])
        warn = f'<p class="neg">Advarsler: {codes}</p>'
    body = (
        f"<h1>Avregning {month} – sammendrag</h1>"
        f'<p class="muted">Status: {_esc(result["status"])}</p>'
        '<dl class="kv">'
        f"<dt>Fakturert energi</dt><dd>{_esc(result['invoice_kwh'] or '–')} kWh</dd>"
        f"<dt>Målt energi (Zaptec)</dt><dd>{_esc(result['grid_kwh'] or '–')} kWh</dd>"
        f"<dt>Sum fakturalinjer</dt><dd>{_nok(result['invoice_lines_total_nok'])}</dd>"
        f"<dt>Sum belastet medlemmer</dt><dd>{_nok(result['total_charged_nok'])}</dd>"
        "</dl>"
        f"{warn}"
        "<h2>Per medlem</h2>"
        '<table><thead><tr><th>Medlem</th><th class="num">kWh</th>'
        '<th class="num">Belastet</th><th class="num">Saldo etter</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )
    return _page(f"Avregning {result['period_month']} – sammendrag", body)


def _write_pdf_sibling(out_dir: Path, stem: str, html_doc: str) -> None:
    """Best-effort: write ``<stem>.pdf`` next to ``<stem>.html``. A PDF failure
    must never break a settlement post, so every exception is swallowed."""
    from ladelaug_avregning.reports.pdf import PDF_AVAILABLE, html_to_pdf

    if not PDF_AVAILABLE:
        return
    with contextlib.suppress(Exception):  # PDF is a nice-to-have at post time
        (out_dir / f"{stem}.pdf").write_bytes(html_to_pdf(html_doc, base_url=str(out_dir)))


def write_reports(
    result: dict[str, Any],
    members: list[dict[str, Any]],
    out_dir: Path,
    forecasts: dict[int, dict[str, Any]] | None = None,
) -> list[str]:
    """Write the summary + one file per member. Returns the relative filenames.

    ``forecasts`` maps ``member_id`` to a
    :meth:`ForecastRepo.member_forecast` dict; each member's entry is rendered
    into their report's forecast section (decision C10).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    forecasts = forecasts or {}
    written: list[str] = []

    summary_html = render_summary_report(result)
    (out_dir / "sammendrag.html").write_text(summary_html, encoding="utf-8")
    written.append("sammendrag.html")
    _write_pdf_sibling(out_dir, "sammendrag", summary_html)

    by_id = {m["member_id"]: m for m in result["members"]}
    for snap in members:
        m = by_id.get(snap["member_id"])
        if m is None:
            continue
        stem = f"medlem-{snap['member_id']}"
        member_html = render_member_report(result, m, forecasts.get(snap["member_id"]))
        (out_dir / f"{stem}.html").write_text(member_html, encoding="utf-8")
        written.append(f"{stem}.html")
        _write_pdf_sibling(out_dir, stem, member_html)
    return written
