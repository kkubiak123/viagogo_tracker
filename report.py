#!/usr/bin/env python3
"""Generator raportow HTML z cenami biletow i linkami afiliacyjnymi — TicketWay."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


EVENTS_FILE = "events.json"
DB_FILE = "prices.db"
REPORTS_DIR = "reports"
CHARTS_DIR = "reports/charts"

SITE_NAME = "TicketWay"
SITE_TAGLINE = "Porównaj ceny biletów — Viagogo, StubHub, Ticombo"
SITE_DESCRIPTION = (
    "Aktualne ceny biletów na mecze Polska i FIFA World Cup 2026. "
    "Porównaj oferty Viagogo, StubHub i Ticombo w jednym miejscu."
)


def _affiliate_url(base_url: str, platform: str, affiliate: dict) -> str:
    if not base_url or base_url.startswith("WSTAW"):
        return "#"
    aid = affiliate.get(f"{platform.lower()}_aid", "")
    if not aid or aid.startswith("WSTAW"):
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}aid={aid}"


def _get_rates() -> dict:
    """Pobiera aktualne kursy EUR/PLN i USD/PLN. Fallback: 4.25 i 3.90."""
    try:
        from tracker import get_exchange_rate
        return {
            "EUR": get_exchange_rate("EUR", "PLN"),
            "USD": get_exchange_rate("USD", "PLN"),
        }
    except Exception:
        return {"EUR": 4.25, "USD": 3.90}


def _to_pln(price: float, currency: str, rates: dict) -> float:
    """Przelicza cene do PLN uzywajac aktualnych kursow."""
    if currency == "PLN":
        return price
    rate = rates.get(currency)
    if rate:
        return price * rate
    return price * rates.get("EUR", 4.25)


def _fmt_pln(amount: float) -> str:
    """Formatuje kwote w PLN: '1 234 zł'."""
    return f"{int(amount):,} zł".replace(",", "\u202f")


def _fmt_orig(price: float, currency: str) -> str:
    """Formatuje cene w oryginalnej walucie."""
    return f"{price:,.2f} {currency}".replace(",", "\u202f")


def _load_db_latest(db_file: str) -> Dict[str, Dict[str, dict]]:
    """Zwraca slownik {event_id: {platform: {price, currency, timestamp}}}."""
    if not Path(db_file).exists():
        return {}
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM prices WHERE id IN "
        "(SELECT MAX(id) FROM prices GROUP BY event_id, platform) "
        "ORDER BY event_id, platform"
    ).fetchall()
    conn.close()
    result: Dict[str, Dict] = {}
    for row in rows:
        eid = row["event_id"]
        if eid not in result:
            result[eid] = {}
        result[eid][row["platform"]] = {
            "price": row["floor_price"],
            "currency": row["currency"],
            "timestamp": row["timestamp"],
        }
    return result


def _platform_logo(platform: str) -> str:
    logos = {"Viagogo": "V", "StubHub": "S", "Ticombo": "T"}
    return logos.get(platform, platform[0])


def generate_index(
    events_file: str = EVENTS_FILE,
    db_file: str = DB_FILE,
    output_dir: str = REPORTS_DIR,
    charts_dir: str = CHARTS_DIR,
) -> Optional[str]:
    """Generuje reports/index.html — publiczna strona TicketWay."""
    try:
        cfg = json.loads(Path(events_file).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Blad ladowania {events_file}: {e}")
        return None

    Path(output_dir).mkdir(exist_ok=True)
    Path(charts_dir).mkdir(parents=True, exist_ok=True)

    affiliate = cfg.get("affiliate", {})
    events = cfg.get("events", [])
    db_data = _load_db_latest(db_file)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    platforms = ["Viagogo", "StubHub", "Ticombo"]
    rates = _get_rates()

    # Generuj wykresy
    from plot import generate_event_chart
    chart_paths: Dict[str, str] = {}
    for ev in events:
        path = generate_event_chart(
            event_id=ev["id"],
            event_name=ev["name"],
            db_file=db_file,
            charts_dir=charts_dir,
        )
        if path:
            chart_paths[ev["id"]] = path

    # Sekcje per-event
    event_sections = ""
    nav_links = ""

    active_events = [ev for ev in events if ev.get("active", False)]

    for ev in active_events:
        eid = ev["id"]
        name = ev["name"]
        date_raw = ev.get("date", "")
        competition = ev.get("competition", "")
        venue = ev.get("venue", "")
        urls = ev.get("urls", {})
        prices = db_data.get(eid, {})

        # Formatuj date po polsku
        try:
            dt = datetime.strptime(date_raw, "%Y-%m-%d")
            date_str = dt.strftime("%-d %B %Y").replace(
                "January", "stycznia").replace("February", "lutego").replace(
                "March", "marca").replace("April", "kwietnia").replace(
                "May", "maja").replace("June", "czerwca").replace(
                "July", "lipca").replace("August", "sierpnia").replace(
                "September", "września").replace("October", "października").replace(
                "November", "listopada").replace("December", "grudnia")
        except ValueError:
            date_str = date_raw

        # Znajdz najlepsza cene
        best_price_pln = None
        best_platform = None
        for pl in platforms:
            if pl in prices:
                p = prices[pl]
                pln_est = _to_pln(p["price"], p["currency"], rates)
                if best_price_pln is None or pln_est < best_price_pln:
                    best_price_pln = pln_est
                    best_platform = pl

        # Nav link
        nav_links += f'<a href="#{eid}" class="nav-link">{name}</a>'

        # Karty platform
        platform_cards = ""
        for pl in platforms:
            url = _affiliate_url(urls.get(pl.lower(), "#"), pl, affiliate)
            if pl in prices:
                p = prices[pl]
                pln_est = _to_pln(p["price"], p["currency"], rates)
                is_best = pl == best_platform
                best_class = " best-card" if is_best else ""
                best_badge = '<span class="best-badge">Najtaniej</span>' if is_best else ""
                pln_str = _fmt_pln(pln_est)
                orig_str = (
                    f'<div class="p-orig">{_fmt_orig(p["price"], p["currency"])}</div>'
                    if p["currency"] != "PLN" else ""
                )
                ts = p["timestamp"][:16]
                btn_label = "Kup bilet →" if url != "#" else "Niedostępny"
                btn_class = "buy-btn" if url != "#" else "buy-btn btn-disabled"
                platform_cards += f"""
        <div class="p-card{best_class}">
          {best_badge}
          <div class="p-logo">{_platform_logo(pl)}</div>
          <div class="p-name">{pl}</div>
          <div class="p-price">{pln_str}</div>
          {orig_str}
          <div class="p-ts">aktualizacja {ts}</div>
          <a href="{url}" target="_blank" rel="noopener sponsored" class="{btn_class}">{btn_label}</a>
        </div>"""
            else:
                platform_cards += f"""
        <div class="p-card p-empty">
          <div class="p-logo">{_platform_logo(pl)}</div>
          <div class="p-name">{pl}</div>
          <div class="p-price">brak danych</div>
          <a href="{url}" target="_blank" rel="noopener" class="buy-btn btn-secondary">Sprawdź</a>
        </div>"""

        # Wykres
        chart_tag = ""
        chart_rel = chart_paths.get(eid, "")
        if chart_rel:
            chart_filename = Path(chart_rel).name
            chart_tag = f"""
      <div class="chart-wrap">
        <h3 class="chart-title">Historia cen (PLN)</h3>
        <img src="charts/{chart_filename}" alt="Wykres cen — {name}" class="chart" loading="lazy">
      </div>"""

        event_sections += f"""
<section id="{eid}" class="event-section">
  <div class="event-header">
    <div>
      <h2 class="event-name">{name}</h2>
      <div class="event-meta">
        <span>📅 {date_str}</span>
        <span>🏟 {venue}</span>
        <span>🏆 {competition}</span>
      </div>
    </div>
    {f'<div class="event-best-price"><span class="ebp-label">od</span><span class="ebp-value">{_fmt_pln(best_price_pln)}</span></div>' if best_price_pln else ""}
  </div>
  <div class="platform-cards">
    {platform_cards}
  </div>
  {chart_tag}
</section>
"""

    # Zbiorczy licznik eventów
    total_active = len(active_events)

    html = f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{SITE_DESCRIPTION}">
  <meta name="robots" content="index, follow">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{SITE_NAME} — {SITE_TAGLINE}">
  <meta property="og:description" content="{SITE_DESCRIPTION}">
  <title>{SITE_NAME} — {SITE_TAGLINE}</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎟</text></svg>">
  <style>
    :root {{
      --bg: #0d0d1a;
      --surface: #16162a;
      --surface2: #1e1e38;
      --accent: #e74c3c;
      --green: #2ecc71;
      --blue: #3498db;
      --text: #f0f0f0;
      --muted: #888;
      --border: #2a2a4a;
      --radius: 12px;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }}

    /* NAV */
    nav {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
      display: flex;
      align-items: center;
      gap: 24px;
      flex-wrap: wrap;
      min-height: 56px;
    }}
    .nav-brand {{
      font-size: 1.25em;
      font-weight: 800;
      color: var(--accent);
      text-decoration: none;
      letter-spacing: -0.02em;
      padding: 12px 0;
    }}
    .nav-link {{
      color: var(--muted);
      text-decoration: none;
      font-size: .9em;
      padding: 4px 0;
      border-bottom: 2px solid transparent;
      transition: color .15s, border-color .15s;
    }}
    .nav-link:hover {{ color: var(--text); border-color: var(--accent); }}

    /* HERO */
    .hero {{
      background: linear-gradient(135deg, #0d0d1a 0%, #1a0a2e 100%);
      padding: 56px 24px 48px;
      text-align: center;
      border-bottom: 1px solid var(--border);
    }}
    .hero h1 {{
      font-size: clamp(1.8em, 5vw, 3em);
      font-weight: 800;
      margin-bottom: 12px;
      background: linear-gradient(90deg, #fff 0%, #aaa 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .hero p {{
      color: var(--muted);
      font-size: 1.05em;
      max-width: 520px;
      margin: 0 auto 24px;
    }}
    .hero-stats {{
      display: inline-flex;
      gap: 32px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 28px;
    }}
    .stat {{ text-align: center; }}
    .stat-value {{ font-size: 1.5em; font-weight: 700; color: var(--text); }}
    .stat-label {{ font-size: .75em; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}

    /* MAIN */
    main {{ max-width: 960px; margin: 0 auto; padding: 40px 20px; }}

    /* EVENT SECTION */
    .event-section {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 28px;
      margin-bottom: 32px;
    }}
    .event-header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 24px;
    }}
    .event-name {{
      font-size: 1.35em;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    .event-meta {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: .85em;
    }}
    .event-meta span {{ white-space: nowrap; }}
    .event-best-price {{
      text-align: right;
      flex-shrink: 0;
    }}
    .ebp-label {{
      display: block;
      font-size: .75em;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: .05em;
    }}
    .ebp-value {{
      display: block;
      font-size: 1.8em;
      font-weight: 800;
      color: var(--green);
    }}

    /* PLATFORM CARDS */
    .platform-cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }}
    .p-card {{
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px 16px;
      text-align: center;
      position: relative;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .p-card.best-card {{
      border-color: var(--green);
      box-shadow: 0 0 20px rgba(46, 204, 113, .2);
    }}
    .p-card.p-empty {{ opacity: .45; }}
    .best-badge {{
      position: absolute;
      top: -10px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--green);
      color: #000;
      font-size: .7em;
      font-weight: 700;
      padding: 2px 10px;
      border-radius: 10px;
      white-space: nowrap;
      text-transform: uppercase;
      letter-spacing: .05em;
    }}
    .p-logo {{
      width: 36px;
      height: 36px;
      background: var(--border);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 1em;
      margin: 0 auto 4px;
    }}
    .p-name {{ font-size: .8em; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }}
    .p-price {{ font-size: 1.5em; font-weight: 800; color: var(--text); margin: 4px 0; }}
    .p-orig {{ font-size: .8em; color: var(--muted); }}
    .p-ts {{ font-size: .7em; color: var(--muted); margin-top: auto; }}
    .buy-btn {{
      display: block;
      background: var(--accent);
      color: #fff;
      padding: 8px 16px;
      border-radius: 8px;
      text-decoration: none;
      font-size: .88em;
      font-weight: 600;
      margin-top: 8px;
      transition: opacity .15s, transform .1s;
    }}
    .buy-btn:hover {{ opacity: .85; transform: translateY(-1px); }}
    .btn-secondary {{ background: var(--border); }}
    .btn-disabled {{ background: #333; cursor: not-allowed; pointer-events: none; color: var(--muted); }}

    /* CHART */
    .chart-wrap {{ margin-top: 8px; }}
    .chart-title {{ font-size: .85em; color: var(--muted); margin-bottom: 8px; font-weight: 500; text-transform: uppercase; letter-spacing: .05em; }}
    .chart {{ width: 100%; border-radius: 8px; display: block; }}

    /* FOOTER */
    footer {{
      border-top: 1px solid var(--border);
      padding: 32px 24px;
      text-align: center;
    }}
    .footer-rates {{
      display: inline-flex;
      gap: 20px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 20px;
      font-size: .82em;
      color: var(--muted);
      margin-bottom: 20px;
    }}
    .footer-rates strong {{ color: var(--text); }}
    .disclaimer {{
      max-width: 600px;
      margin: 0 auto;
      font-size: .78em;
      color: var(--muted);
      line-height: 1.7;
    }}
    .disclaimer a {{ color: var(--muted); }}
    .updated {{ font-size: .75em; color: var(--muted); margin-top: 16px; }}

    /* MOBILE */
    @media (max-width: 600px) {{
      nav {{ gap: 12px; padding: 0 16px; }}
      .hero {{ padding: 36px 16px 32px; }}
      .hero-stats {{ gap: 20px; padding: 12px 20px; flex-wrap: wrap; }}
      main {{ padding: 24px 16px; }}
      .event-section {{ padding: 20px 16px; }}
      .event-best-price {{ display: none; }}
      .platform-cards {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 400px) {{
      .platform-cards {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>

<nav>
  <a href="#" class="nav-brand">🎟 {SITE_NAME}</a>
  {nav_links}
</nav>

<div class="hero">
  <h1>Porównaj ceny biletów</h1>
  <p>Aktualne oferty z Viagogo, StubHub i Ticombo — w jednym miejscu, przeliczone na złotówki.</p>
  <div class="hero-stats">
    <div class="stat">
      <div class="stat-value">{total_active}</div>
      <div class="stat-label">Śledzone mecze</div>
    </div>
    <div class="stat">
      <div class="stat-value">3</div>
      <div class="stat-label">Platformy</div>
    </div>
    <div class="stat">
      <div class="stat-value">1h</div>
      <div class="stat-label">Aktualizacja</div>
    </div>
  </div>
</div>

<main>
{event_sections}
</main>

<footer>
  <div class="footer-rates">
    <span>EUR/PLN: <strong>{rates["EUR"]:.4f}</strong></span>
    <span>USD/PLN: <strong>{rates["USD"]:.4f}</strong></span>
  </div>
  <p class="disclaimer">
    Strona zawiera linki partnerskie (afiliacyjne). Gdy kupisz bilet przez nasz link,
    możemy otrzymać prowizję bez żadnych dodatkowych kosztów dla Ciebie.
    Ceny są aktualizowane automatycznie co godzinę i mogą różnić się od cen aktualnie
    dostępnych na platformach. Zawsze sprawdź ostateczną cenę przed zakupem.
  </p>
  <p class="updated">Ostatnia aktualizacja danych: {now}</p>
</footer>

</body>
</html>"""

    out = Path(output_dir) / "index.html"
    out.write_text(html, encoding="utf-8")
    return str(out)


# Alias dla kompatybilnosci z tracker.py
def generate_reports(
    events_file: str = EVENTS_FILE,
    db_file: str = DB_FILE,
    output_dir: str = REPORTS_DIR,
) -> Optional[str]:
    return generate_index(events_file, db_file, output_dir)


if __name__ == "__main__":
    path = generate_index()
    if path:
        print(f"Raport: {path}")
