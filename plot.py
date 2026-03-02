#!/usr/bin/env python3
"""Generator wykresow cen biletow per wydarzenie z danych SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# Zachowane dla kompatybilnosci wstecznej z testami
DEFAULT_CSV = "viagogo_prices.csv"
DEFAULT_CHART = "chart.png"

PLATFORM_COLORS = {
    "Viagogo": "#e74c3c",
    "StubHub": "#2980b9",
    "Ticombo": "#27ae60",
}


def generate_event_chart(
    event_id: str,
    event_name: str,
    db_file: str = "prices.db",
    output_path: Optional[str] = None,
    charts_dir: str = "reports/charts",
) -> Optional[str]:
    """
    Generuje wykres historii cen dla jednego wydarzenia.
    Kazda platforma to osobna linia na wykresie.

    Zwraca sciezke do wygenerowanego pliku PNG lub None przy bledzie.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("Brak matplotlib. Uruchom: pip install matplotlib")
        return None

    if not Path(db_file).exists():
        return None

    # Pobierz kursy walut
    rates: dict = {"EUR": 4.25, "USD": 3.90}
    try:
        from tracker import get_exchange_rate
        rates["EUR"] = get_exchange_rate("EUR", "PLN")
        rates["USD"] = get_exchange_rate("USD", "PLN")
    except Exception:
        pass

    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, platform, floor_price, currency FROM prices "
        "WHERE event_id=? ORDER BY timestamp ASC",
        (event_id,),
    ).fetchall()
    conn.close()

    if len(rows) < 2:
        return None

    def to_pln(price: float, currency: str) -> float:
        if currency == "PLN":
            return price
        rate = rates.get(currency)
        if rate:
            return price * rate
        return price * rates["EUR"]

    # Grupuj dane per platforma (przeliczone do PLN)
    platforms: dict = {}
    for row in rows:
        p = row["platform"]
        if p not in platforms:
            platforms[p] = {"times": [], "prices": []}
        try:
            ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        platforms[p]["times"].append(ts)
        platforms[p]["prices"].append(to_pln(row["floor_price"], row["currency"]))

    if not platforms:
        return None

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    for platform, data in platforms.items():
        if len(data["times"]) < 1:
            continue
        color = PLATFORM_COLORS.get(platform, "#ffffff")
        ax.plot(
            data["times"], data["prices"],
            marker="o", markersize=3, linewidth=2,
            color=color, label=platform,
        )

    ax.set_title(event_name, color="white", fontsize=14, pad=12)
    ax.set_xlabel("Data pomiaru", color="#aaa", fontsize=10)
    ax.set_ylabel("Cena w PLN (floor price)", color="#aaa", fontsize=10)
    ax.tick_params(colors="#aaa")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M"))
    fig.autofmt_xdate(rotation=30)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333")
    ax.grid(True, color="#2a2a4a", linewidth=0.5, alpha=0.7)
    ax.legend(facecolor="#1a1a2e", labelcolor="white", fontsize=9)

    plt.tight_layout()

    if output_path is None:
        Path(charts_dir).mkdir(parents=True, exist_ok=True)
        output_path = str(Path(charts_dir) / f"chart_{event_id}.png")

    plt.savefig(output_path, dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return output_path


def generate_all_charts(
    events: list,
    db_file: str = "prices.db",
    charts_dir: str = "reports/charts",
) -> dict:
    """
    Generuje wykresy dla wszystkich wydarzen z listy.
    Zwraca slownik {event_id: sciezka_do_png}.
    """
    results = {}
    for event in events:
        eid = event["id"]
        path = generate_event_chart(
            event_id=eid,
            event_name=event["name"],
            db_file=db_file,
            charts_dir=charts_dir,
        )
        if path:
            results[eid] = path
    return results


# ---------------------------------------------------------------------------
# Backwards-compat: stary interfejs CSV (uzywany przez testy)
# ---------------------------------------------------------------------------

def generate_chart(
    csv_file: str = DEFAULT_CSV,
    chart_file: str = DEFAULT_CHART,
) -> bool:
    """Zachowane dla kompatybilnosci wstecznej z testami. Czyta z CSV."""
    try:
        import csv as csv_module
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        times, prices = [], []
        with open(csv_file, encoding="utf-8") as f:
            for row in csv_module.DictReader(f):
                try:
                    times.append(datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S"))
                    prices.append(float(row["floor_price"]))
                except (ValueError, KeyError):
                    continue

        if len(times) < 2:
            return False

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(times, prices, marker="o", markersize=3, color="#e74c3c")
        ax.set_title("Floor price history", fontsize=14)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M"))
        fig.autofmt_xdate(rotation=30)
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(chart_file, dpi=110, bbox_inches="tight")
        plt.close(fig)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import json
    cfg = json.loads(Path("events.json").read_text(encoding="utf-8"))
    charts = generate_all_charts(cfg.get("events", []))
    for eid, path in charts.items():
        print(f"  {eid}: {path}")
