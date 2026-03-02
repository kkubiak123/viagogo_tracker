# Ticket Price Tracker

Automatyczny tracker cen biletów na wtórnym rynku biletowym (Viagogo, StubHub, Ticombo).
Scraping co godzinę, zapis do SQLite, wykresy per wydarzenie, raport HTML z linkami afiliacyjnymi.

---

## Stan projektu

| Faza | Status | Opis |
|------|--------|------|
| Tracker wielu wydarzeń | ✅ Gotowe | events.json + SQLite + wykresy per mecz |
| Rejestracja afiliacyjna | ✅ Gotowe | Viagogo (CJ Affiliate), StubHub (Partnerize) |
| Raporty HTML | ✅ Gotowe | Tabela + wykresy + linki afiliacyjne |
| Deployment publiczny | 🔜 Planowane | VPS lub GitHub Pages |

---

## Struktura projektu

```
viagogo-tracker/
├── tracker.py        # Główny scraper + harmonogram
├── plot.py           # Generator wykresów z SQLite (per wydarzenie)
├── report.py         # Generator raportu HTML
├── db.py             # Warstwa SQLite
├── events.json       # Lista śledzonych wydarzeń z URL-ami
├── test_tracker.py   # Testy jednostkowe (42/42)
├── setup.sh          # Skrypt instalacyjny (macOS)
└── README.md

# Tworzone automatycznie (wykluczone z git):
├── prices.db         # Baza danych SQLite
├── tracker.log       # Logi
└── reports/
    ├── index.html    # Raport HTML
    └── charts/       # Wykresy PNG per wydarzenie
```

---

## Instalacja

```bash
cd ~/Desktop/Antrop/viagogo-tracker
bash setup.sh
```

Instaluje: Python, venv, Playwright + Chromium, matplotlib, pandas, pytest.

---

## Konfiguracja

### Dodawanie wydarzeń — events.json

```json
{
  "settings": {
    "interval_minutes": 60
  },
  "affiliate": {
    "viagogo_aid": "TWOJ_AID",
    "stubhub_aid": "TWOJ_AID"
  },
  "events": [
    {
      "id": "unikalny-id",
      "name": "Polska - Albania",
      "date": "2026-03-26",
      "time": "20:45",
      "venue": "PGE Narodowy, Warszawa",
      "competition": "Baraże MŚ 2026",
      "active": true,
      "urls": {
        "viagogo": "https://www.viagogo.com/...",
        "stubhub": "https://www.stubhub.com/...",
        "ticombo": "https://www.ticombo.com/..."
      }
    }
  ]
}
```

- `active: false` — wydarzenie śledzone ale pomijane w cyklu scrapowania
- `aid` w sekcji `affiliate` — dodawany automatycznie do wszystkich linków w raporcie HTML

### Aktualnie śledzone wydarzenia

| Wydarzenie | Data | Platformy |
|-----------|------|-----------|
| Polska - Albania (półfinał baraży MŚ) | 26.03.2026 | Viagogo, StubHub, Ticombo |
| FIFA World Cup 2026 - Finał | 19.07.2026 | Viagogo, Ticombo |

---

## Uruchomienie

```bash
source venv/bin/activate
python tracker.py
```

Tracker co godzinę:
1. Iteruje po aktywnych wydarzeniach z `events.json`
2. Scrapuje ceny ze wszystkich platform (Viagogo, StubHub, Ticombo)
3. Zapisuje do `prices.db`
4. Generuje wykresy PNG per wydarzenie (`reports/charts/`)
5. Generuje raport HTML (`reports/index.html`)

Zatrzymanie: **Ctrl+C**

---

## Ręczne generowanie raportów

```bash
source venv/bin/activate

# Raport HTML + wykresy
python report.py

# Tylko wykresy
python plot.py
```

---

## Testy

```bash
source venv/bin/activate
pytest test_tracker.py -v
```

---

## Podgląd bazy danych

```bash
# Ostatnie ceny per wydarzenie i platforma
sqlite3 prices.db "SELECT event_id, platform, floor_price, currency, timestamp FROM prices WHERE id IN (SELECT MAX(id) FROM prices GROUP BY event_id, platform);"

# Historia cen dla konkretnego wydarzenia
sqlite3 prices.db "SELECT timestamp, platform, floor_price, currency FROM prices WHERE event_id='pol-alb-2026-03-26' ORDER BY timestamp DESC LIMIT 20;"
```

---

## Programy afiliacyjne

| Platforma | Sieć | Prowizja |
|-----------|------|---------|
| Viagogo | CJ Affiliate (cj.com) | ~7% |
| StubHub | Partnerize (join.partnerize.com/stubhub) | ~4-9% |
| Ticombo | Bezpośredni kontakt | TBD |

Po akceptacji do programu wpisz swój `aid` w `events.json` w sekcji `affiliate`.

---

## Rozwiązywanie problemów

### CAPTCHA / blokada bota
- Zwiększ opóźnienie: `random.uniform(15, 30)` w `tracker.py`
- Zmień `USER_AGENT` na nowszą wersję Chrome
- Odczekaj kilka godzin

### Brak ceny (None)
- Sprawdź URL ręcznie w przeglądarce
- Zwiększ timeout: `timeout=60000` w `scrape_viagogo()`

### Logi
```bash
tail -50 tracker.log
```

---

## Linki

- **GitHub:** https://github.com/kkubiak123/viagogo_tracker
- **CJ Affiliate:** https://www.cj.com
- **StubHub Partnerize:** https://join.partnerize.com/stubhub
