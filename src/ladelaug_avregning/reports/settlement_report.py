"""HTML settlement reports.

``render_member_report`` / ``render_summary_report`` are pure functions over the
``SettlementRepo.compute`` result; ``write_reports`` persists them under
``state/reports/<period>/`` at post time.
"""

from __future__ import annotations

import html
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

from ladelaug_avregning.money import ore_to_nok

log = logging.getLogger(__name__)

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font: 15px/1.5 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #1a1a1a; background: #fff; margin: 0; padding: 2rem; }
.wrap { max-width: 720px; margin: 0 auto; position: relative; z-index: 1; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.75rem 0 .5rem; border-bottom: 1px solid #e2e2e2;
     padding-bottom: .25rem; }
.muted { color: #666; }
table { width: 100%; border-collapse: collapse; margin: .5rem 0; }
th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #ededed; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.total td, .total td { font-weight: 600; border-top: 2px solid #ccc; border-bottom: none; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: .2rem 1.5rem; }
.kv dt { color: #666; }
.kv dt .sub { display: block; font-size: .85rem; }
.kv dd { margin: 0; text-align: right; font-variant-numeric: tabular-nums; }
/* Amounts: "kr" a fixed hair-space left of the digits, the digits in a
   fixed-width right-aligned box, so both the prefix and the øre line up down
   every (right-aligned) column with only a small constant gap between them. */
.money { white-space: nowrap; }
.money .cur { padding-right: .5ch; }
.money .amt { display: inline-block; min-width: 9ch; text-align: right; }
.neg { color: #b00020; }
footer { margin-top: 2.5rem; font-size: .85rem; color: #888; }
.draft-banner { border: 2px solid #b8860b; background: #fff8e1; color: #6b5200;
    padding: .75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem;
    font-weight: 600; }
.draft-watermark { position: fixed; top: 45%; left: 50%; z-index: 0;
    transform: translate(-50%, -50%) rotate(-28deg); font-size: 6rem;
    font-weight: 800; letter-spacing: .12em; color: rgba(184, 134, 11, .12);
    white-space: nowrap; pointer-events: none; }
"""


def _esc(v: Any) -> str:
    return html.escape(str(v))


def _dec(v: Any) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except (ArithmeticError, ValueError):
        return Decimal(0)


def _pct(part: Decimal, whole: Decimal) -> str:
    """``part`` of ``whole`` as a 1-decimal percentage string, ``"0,0"`` when
    ``whole`` is zero. nb-NO decimal comma."""
    if whole <= 0:
        return "0,0"
    return f"{(part / whole * 100).quantize(Decimal('0.1'))}".replace(".", ",")


def _kwh(v: Any) -> str:
    """Trim trailing zeros without ever going to scientific notation."""
    d = _dec(v)
    s = f"{d:.2f}".rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


def _nok(value: str | int) -> str:
    """Format a NOK decimal string as an aligned ``kr 1 234,56`` cell (nb-NO —
    currency symbol first). Returns an HTML ``<span class="money">``: ``kr`` a
    fixed hair-space left of a fixed-width, right-aligned digit box, so in a
    right-aligned column both the prefix and the øre line up with only a small
    constant gap between them."""
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
    number = ("-" if neg else "") + " ".join(groups) + f",{frac}"
    return (
        f'<span class="money"><span class="cur">kr</span><span class="amt">{number}</span></span>'
    )


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


def _basis(result: dict[str, Any], member: dict[str, Any]) -> dict[str, Any]:
    """Settlement-wide aggregates a member is entitled to see: the fixed vs.
    consumption cost split, participant counts, and the member's share of the
    total metered energy."""
    breakdown = result.get("lines") or []
    equal_ore = sum(int(ln["amount_ore"]) for ln in breakdown if ln["kind"] == "equal")
    consumption_ore = sum(int(ln["amount_ore"]) for ln in breakdown if ln["kind"] == "consumption")
    members = result.get("members") or []
    equal_members = sum(1 for m in members if m.get("participates_equal"))
    total_kwh = sum(_dec(m.get("consumption_kwh")) for m in members)
    my_kwh = _dec(member.get("consumption_kwh"))
    return {
        "equal_ore": equal_ore,
        "equal_nok": str(ore_to_nok(equal_ore)),
        "equal_members": equal_members,
        "consumption_ore": consumption_ore,
        "consumption_nok": str(ore_to_nok(consumption_ore)),
        "total_kwh": total_kwh,
        "my_kwh": my_kwh,
        "my_kwh_pct": _pct(my_kwh, total_kwh),
        "breakdown": breakdown,
    }


def _invoice_section(invoices: list[dict[str, str]] | None) -> str:
    """``invoices`` is a list of ``{"filename", "href"}`` — the supplier invoice
    files behind this settlement. Empty/None renders nothing."""
    if not invoices:
        return ""
    items = "".join(
        f'<li><a href="{_esc(i["href"])}">{_esc(i["filename"])}</a></li>' for i in invoices
    )
    return (
        "<h2>Faktura fra strømleverandør</h2>"
        f"<p>Grunnlaget for kostnadene over:</p><ul>{items}</ul>"
    )


def render_member_report(
    result: dict[str, Any],
    member: dict[str, Any],
    forecast: dict[str, Any] | None = None,
    *,
    invoices: list[dict[str, str]] | None = None,
    draft: bool = False,
) -> str:
    """``draft=True`` renders the report as an explicitly-marked preview: a
    diagonal ``UTKAST`` watermark, a warning banner, and an ``UTKAST –`` title
    prefix. Used for a frozen-but-unposted settlement the board has shared with
    its members (US-905); the numbers can still change before posting."""
    month = _esc(result["period_month"])
    name = _esc(member["full_name"])
    b = _basis(result, member)

    my_by_line = {ln["invoice_line_id"]: ln for ln in member["lines"]}
    if b["breakdown"]:
        line_rows = "".join(
            '<tr><td>{desc}</td><td class="muted">{typ}</td>'
            '<td class="num">{total}</td><td class="num">{mine}</td></tr>'.format(
                desc=_esc(ln["description"]),
                typ=(f"Likt · delt på {ln['recipients']}" if ln["kind"] == "equal" else "Forbruk"),
                total=_nok(str(ore_to_nok(int(ln["amount_ore"])))),
                mine=(
                    _nok(my_by_line[ln["line_id"]]["amount_nok"])
                    if ln["line_id"] in my_by_line
                    else "–"
                ),
            )
            for ln in b["breakdown"]
        )
    else:
        line_rows = (
            "".join(
                f"<tr><td>{_esc(ln['description'])}</td>"
                f'<td class="muted">{"Likt" if ln["kind"] == "equal" else "Forbruk"}</td>'
                f'<td class="num">–</td><td class="num">{_nok(ln["amount_nok"])}</td></tr>'
                for ln in member["lines"]
            )
            or '<tr><td colspan="4" class="muted">Ingen kostnader denne måneden.</td></tr>'
        )

    invoice_total_nok = result.get("invoice_lines_total_nok")
    after_cls = ' class="neg"' if member["balance_after_ore"] < 0 else ""
    draft_head = (
        '<div class="draft-watermark">UTKAST</div>'
        '<div class="draft-banner">UTKAST — dette er ikke en endelig avregning. '
        "Tallene bygger på et fryst øyeblikksbilde og kan endres før avregningen "
        "bokføres. Du blir varslet når den endelige avregningen er klar.</div>"
        if draft
        else ""
    )
    body = (
        f"{draft_head}"
        f"<h1>Avregning {month}{' (UTKAST)' if draft else ''}</h1>"
        f'<p class="muted">{name}</p>'
        "<h2>Avregningsgrunnlag</h2>"
        '<dl class="kv">'
        f"<dt>Målt energi (Zaptec)</dt>"
        f"<dd>{_kwh(result['grid_kwh']) if result.get('grid_kwh') else '–'} kWh</dd>"
        f"<dt>Faste kostnader (delt likt)"
        f'<span class="sub">delt på {b["equal_members"]} medlemmer</span></dt>'
        f"<dd>{_nok(b['equal_nok'])}</dd>"
        f"<dt>Forbrukskostnader (etter kWh)</dt><dd>{_nok(b['consumption_nok'])}</dd>"
        + (
            f"<dt>Sum fakturagrunnlag</dt><dd>{_nok(invoice_total_nok)}</dd>"
            if invoice_total_nok is not None
            else ""
        )
        + "</dl>"
        f"{_invoice_section(invoices)}"
        "<h2>Ditt forbruk</h2>"
        '<dl class="kv">'
        f"<dt>Ladet energi</dt><dd>{_kwh(member['consumption_kwh'])} kWh</dd>"
        f"<dt>Antall ladeøkter</dt><dd>{_esc(member['session_count'])}</dd>"
        f"<dt>Din andel av totalforbruk</dt><dd>{_kwh(b['my_kwh'])} av "
        f"{_kwh(b['total_kwh'])} kWh ({b['my_kwh_pct']} %)</dd>"
        "</dl>"
        "<h2>Kostnadsfordeling</h2>"
        "<table><thead><tr><th>Post</th><th>Type</th>"
        '<th class="num">Totalbeløp</th><th class="num">Din andel</th>'
        "</tr></thead><tbody>"
        f"{line_rows}"
        f'<tr class="total"><td colspan="3">Sum belastet deg</td>'
        f'<td class="num">{_nok(member["charge_nok"])}</td></tr>'
        "</tbody></table>"
        "<h2>Saldo</h2>"
        '<dl class="kv">'
        f"<dt>Saldo før avregning</dt><dd>{_nok(member['balance_before_nok'])}</dd>"
        f"<dt>Belastet</dt><dd>{_nok('-' + str(member['charge_nok']))}</dd>"
        f"<dt>Saldo etter avregning</dt><dd{after_cls}>{_nok(member['balance_after_nok'])}</dd>"
        "</dl>"
        f"{_forecast_section(forecast)}"
    )
    prefix = "UTKAST – " if draft else ""
    return _page(f"{prefix}Avregning {result['period_month']} – {member['member_reference']}", body)


def render_summary_report(result: dict[str, Any]) -> str:
    month = _esc(result["period_month"])
    rows = "".join(
        f"<tr><td>{_esc(m['member_reference'])} {_esc(m['full_name'])}</td>"
        f'<td class="num">{_kwh(m["consumption_kwh"])}</td>'
        f'<td class="num">{_nok(m["charge_nok"])}</td>'
        f'<td class="num{" neg" if m["balance_after_ore"] < 0 else ""}">'
        f"{_nok(m['balance_after_nok'])}</td></tr>"
        for m in result["members"]
    )
    warn = ""
    if result["warnings"]:
        codes = ", ".join(_esc(w["code"]) for w in result["warnings"])
        warn = f'<p class="neg">Advarsler: {codes}</p>'
    breakdown = result.get("lines") or []
    equal_ore = sum(int(ln["amount_ore"]) for ln in breakdown if ln["kind"] == "equal")
    consumption_ore = sum(int(ln["amount_ore"]) for ln in breakdown if ln["kind"] == "consumption")
    equal_members = sum(1 for m in result["members"] if m.get("participates_equal"))
    body = (
        f"<h1>Avregning {month} – sammendrag</h1>"
        f'<p class="muted">Status: {_esc(result["status"])}</p>'
        '<dl class="kv">'
        f"<dt>Fakturert energi</dt>"
        f"<dd>{_kwh(result['invoice_kwh']) if result['invoice_kwh'] else '–'} kWh</dd>"
        f"<dt>Målt energi (Zaptec)</dt>"
        f"<dd>{_kwh(result['grid_kwh']) if result['grid_kwh'] else '–'} kWh</dd>"
        f"<dt>Faste kostnader (delt likt)"
        f'<span class="sub">delt på {equal_members} medlemmer</span></dt>'
        f"<dd>{_nok(str(ore_to_nok(equal_ore)))}</dd>"
        f"<dt>Forbrukskostnader (etter kWh)</dt>"
        f"<dd>{_nok(str(ore_to_nok(consumption_ore)))}</dd>"
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
    must never break a settlement post — it is logged, not raised."""
    from ladelaug_avregning.reports.pdf import PDF_AVAILABLE, html_to_pdf

    if not PDF_AVAILABLE:
        return
    try:
        (out_dir / f"{stem}.pdf").write_bytes(html_to_pdf(html_doc, base_url=str(out_dir)))
    except Exception as exc:  # noqa: BLE001 - PDF is a nice-to-have at post time
        log.warning("post-time PDF %s.pdf failed to render: %s", stem, exc)


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
