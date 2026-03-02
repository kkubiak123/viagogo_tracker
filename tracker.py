#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Viagogo Ticket Price Tracker
============================================================
Śledzi najniższą dostępną cenę biletu (floor price) na Viagogo
i zapisuje historię pomiarów do pliku CSV.

Użycie:
    python tracker.py

Zatrzymanie:
    Ctrl+C
"""

import csv
import json
import logging
import random
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# =============================================================================
# Konfiguracja — edytuj według potrzeb
# =============================================================================

EVENTS_FILE = "events.json"        # Lista meczow i URL-ow
DB_FILE = "prices.db"              # Baza SQLite
CHART_FILE = "chart.png"           # Wykres (backwards compat)
REPORTS_DIR = "reports"            # Katalog raportow HTML

# Legacy CSV -- zachowane dla kompatybilnosci z testami
VIAGOGO_CSV = "viagogo_prices.csv"
TICOMBO_CSV = "ticombo_prices.csv"

# Legacy URL -- uzywane gdy brak events.json
EVENT_URL = (
    "https://www.viagogo.com/in/Sports-Tickets/Soccer/Soccer-Tournament/"
    "World-Cup-Tickets/E-153020449"
)
TICOMBO_URL = (
    "https://www.ticombo.com/en/sports-tickets/football-tickets/final-world-cup-2026"
)

# Wartosci domyslne -- nadpisywane przez events.json
INTERVAL_MINUTES = 60
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300
_PLACEHOLDER = "WSTAW"

# =============================================================================
# Konfiguracja logowania
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# =============================================================================
# Stałe
# =============================================================================

# Realistyczny User-Agent dla Chrome 120 na macOS (anty-bot)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Mapa symboli walut → kody ISO 4217
CURRENCY_SYMBOLS: Dict[str, str] = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₩": "KRW",
    "₺": "TRY",
    "₽": "RUB",
    "A$": "AUD",
    "C$": "CAD",
    "zł": "PLN",   # Złoty polski
    "Ft": "HUF",   # Forint węgierski
    "kr": "SEK",   # Korona (SE/NO/DK)
}

# Wszystkie kody ISO walut obsługiwane w parsowaniu
ISO_CURRENCY_CODES = (
    "EUR|USD|GBP|INR|JPY|AUD|CAD|CHF|CNY|KRW|TRY|RUB"
    "|PLN|HUF|SEK|NOK|DKK|CZK|BRL|MXN|SGD|HKD|THB|ILS"
)

# Regex dla wieloznakowych i jednobajtowych symboli walut
_MULTI_SYMBOL_RE = r"(?:zł|Ft|A\$|C\$|kr|€|\$|£|¥|₹|₩|₺|₽)"

# Selektory CSS do szukania ceny w DOM (fallback)
PRICE_CSS_SELECTORS = [
    "[itemprop='lowPrice']",
    "[itemprop='price']",
    "[class*='FromPrice']",
    "[class*='from-price']",
    "[class*='TicketPrice']",
    "[class*='ticket-price']",
    "[data-testid*='price']",
    "[data-testid*='from']",
    "[class*='Price'] [class*='amount']",
    "[class*='price'] [class*='amount']",
    "span[class*='price']",
    ".price",
    "button",   # Viagogo pokazuje ceny kategorii na przyciskach sektorów
]


# =============================================================================
# Funkcje parsowania (czyste funkcje — łatwo testowalne)
# =============================================================================


def parse_price_from_text(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Wyciąga cenę liczbową i walutę z tekstu.

    Obsługuje formaty:
      €245   $350   £199   245 EUR   From €1,234.50   USD 499

    Zwraca:
      (cena: float, waluta: str) — gdy znaleziono
      (None, None)               — gdy nie znaleziono lub wejście puste
    """
    if not text or not text.strip():
        return None, None

    # Normalizuj niełamiące spacje i usuń słowa poprzedzające cenę
    cleaned = text.replace("\xa0", " ").replace("\u202f", " ")
    cleaned = re.sub(
        r"(?i)\b(from|starting|as low as|min|tickets? from)\b", "", cleaned
    ).strip()

    # Wzorzec 1: Symbol waluty (jedno- lub wieloznakowy) przed liczbą
    # Obsługuje: zł31,392  €245  $1,234.50  kr500
    m = re.search(
        rf"({_MULTI_SYMBOL_RE})\s*([\d]{{1,6}}(?:[,.\s]\d{{3}})*(?:[.,]\d{{1,2}})?)",
        cleaned,
    )
    if m:
        symbol, amount_str = m.groups()
        currency = CURRENCY_SYMBOLS.get(symbol, symbol)
        try:
            price = float(re.sub(r"[,\s]", "", amount_str))
            if price > 0:
                return price, currency
        except ValueError:
            pass

    # Wzorzec 2: Liczba przed symbolem waluty  np. 245€  350zł
    m = re.search(
        rf"([\d]{{1,6}}(?:[,.\s]\d{{3}})*(?:[.,]\d{{1,2}})?)\s*({_MULTI_SYMBOL_RE})",
        cleaned,
    )
    if m:
        amount_str, symbol = m.groups()
        currency = CURRENCY_SYMBOLS.get(symbol, symbol)
        try:
            price = float(re.sub(r"[,\s]", "", amount_str))
            if price > 0:
                return price, currency
        except ValueError:
            pass

    # Wzorzec 3: Kod ISO przed liczbą  np. EUR 245  PLN 31,393  USD 1,234
    m = re.search(
        rf"\b({ISO_CURRENCY_CODES})\s+([\d]{{1,6}}(?:[,.\s]\d{{3}})*(?:[.,]\d{{1,2}})?)",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        currency, amount_str = m.groups()
        try:
            price = float(re.sub(r"[,\s]", "", amount_str))
            if price > 0:
                return price, currency.upper()
        except ValueError:
            pass

    # Wzorzec 4: Liczba przed kodem ISO  np. 245 EUR  31392 PLN
    m = re.search(
        rf"([\d]{{1,6}}(?:[,.\s]\d{{3}})*(?:[.,]\d{{1,2}})?)\s*\b({ISO_CURRENCY_CODES})\b",
        cleaned,
        re.IGNORECASE,
    )
    if m:
        amount_str, currency = m.groups()
        try:
            price = float(re.sub(r"[,\s]", "", amount_str))
            if price > 0:
                return price, currency.upper()
        except ValueError:
            pass

    return None, None


def parse_price_from_html(html: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Wyciąga cenę z fragmentu HTML (np. innerHTML elementu DOM).

    Usuwa tagi HTML i przekazuje czysty tekst do parse_price_from_text().
    Przydatna do testowania z surowym HTML.
    """
    if not html:
        return None, None
    # Usuń tagi HTML
    text = re.sub(r"<[^>]+>", " ", html)
    # Normalizuj białe znaki
    text = " ".join(text.split())
    return parse_price_from_text(text)


def extract_price_from_json(
    data: Any,
) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Szuka danych cenowych i nazwy wydarzenia w słowniku JSON.

    Sprawdza typowe klucze używane przez Viagogo i inne platformy.

    Zwraca:
      (floor_price, currency, event_name) — wartości mogą być None
    """
    if not isinstance(data, dict):
        return None, None, None

    floor_price: Optional[float] = None
    currency: Optional[str] = None
    event_name: Optional[str] = None

    # Szukaj nazwy wydarzenia
    for name_key in ["name", "eventName", "title", "event_name", "eventTitle", "displayName"]:
        val = data.get(name_key)
        if isinstance(val, str) and len(val) > 2:
            event_name = val
            break

    # Szukaj minimalnej ceny biletu
    price_keys = [
        "minPrice", "floorPrice", "floor_price", "fromPrice", "lowestPrice",
        "startingPrice", "minTicketPrice", "ticketFromPrice", "minDisplayPrice",
        "startPrice", "cheapestPrice",
    ]

    for key in price_keys:
        val = data.get(key)
        if val is None:
            continue

        if isinstance(val, (int, float)) and val > 0:
            floor_price = float(val)
            break
        elif isinstance(val, dict):
            # Zagnieżdżony obiekt ceny: {"amount": 245, "currency": "EUR"}
            amount = val.get("amount") or val.get("value") or val.get("displayValue")
            curr = val.get("currency") or val.get("currencyCode")
            if amount is not None:
                try:
                    parsed = float(str(amount).replace(",", "").replace(" ", ""))
                    if parsed > 0:
                        floor_price = parsed
                        if curr:
                            currency = str(curr)
                        break
                except (TypeError, ValueError):
                    pass
        elif isinstance(val, str):
            # Cena jako string: "€245"
            parsed_price, parsed_currency = parse_price_from_text(val)
            if parsed_price:
                floor_price = parsed_price
                if parsed_currency:
                    currency = parsed_currency
                break

    # Szukaj waluty osobno (jeśli nie znaleziono razem z ceną)
    if not currency:
        for curr_key in ["currency", "currencyCode", "currencyIso", "priceCurrency"]:
            val = data.get(curr_key)
            if isinstance(val, str) and 2 <= len(val) <= 4:
                currency = val.upper()
                break

    return floor_price, currency, event_name


# =============================================================================
# Funkcje zapisu danych
# =============================================================================


def save_to_csv(
    timestamp: str,
    event_name: str,
    floor_price: float,
    currency: str,
    platform: str = "",
    csv_file: str = "viagogo_prices.csv",
) -> bool:
    """Zachowane dla kompatybilności wstecznej z testami. Nowy kod używa save_to_db()."""
    csv_path = Path(csv_file)
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0
    try:
        with open(csv_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["timestamp", "event_name", "floor_price", "currency", "platform"],
            )
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp": timestamp,
                "event_name": event_name,
                "floor_price": floor_price,
                "currency": currency,
                "platform": platform,
            })
        return True
    except IOError as e:
        logger.warning(f"Blad zapisu CSV: {e}")
        return False


def save_to_db(timestamp, event_id, event_name, platform, floor_price, currency):
    """Zapisuje pomiar do bazy SQLite."""
    try:
        from db import Database
        with Database(DB_FILE) as db:
            return db.save(timestamp, event_id, event_name, platform, floor_price, currency)
    except Exception as e:
        logger.warning(f"Blad zapisu do DB: {e}")
        return False


# =============================================================================
# Scraper — Playwright
# =============================================================================


def scrape_viagogo(url: str) -> Optional[Dict[str, Any]]:
    """
    Scrapuje stronę Viagogo i zwraca słownik z danymi o najniższej cenie.

    Strategia ekstrakcji ceny (od najlepszej do fallback):
      1. Przechwycenie odpowiedzi JSON z API Viagogo (network intercept)
      2. Dane strukturalne LD+JSON osadzone w stronie
      3. Selektory CSS w DOM

    Anty-bot:
      - Losowe opóźnienie 3–8 s przed żądaniem
      - Realistyczny User-Agent i nagłówki HTTP
      - Ukrycie flagi navigator.webdriver

    Zwraca:
      {"event_name": str, "floor_price": float, "currency": str}
      lub None gdy nie udało się pobrać ceny.
    """
    # Import playwright wewnątrz funkcji — nie blokuje importu modułu bez Playwright
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error(
            "❌ Playwright nie jest zainstalowany. "
            "Uruchom: pip install playwright && playwright install chromium"
        )
        return None

    # Losowe opóźnienie anty-bot
    delay = random.uniform(3, 8)
    logger.info(f"Oczekiwanie {delay:.1f}s przed żądaniem (anty-bot)...")
    time.sleep(delay)

    # Dane zebrane z odpowiedzi sieciowych i DOM
    captured: Dict[str, Any] = {}

    def on_response(response) -> None:
        """
        Callback wywoływany dla każdej odpowiedzi HTTP.
        Szuka danych cenowych w odpowiedziach JSON z API Viagogo.
        """
        try:
            content_type = response.headers.get("content-type", "")
            if response.status != 200 or "json" not in content_type:
                return

            resp_url = response.url.lower()
            # Filtruj tylko odpowiedzi powiązane z biletami i wydarzeniami
            relevant_keywords = ["listing", "ticket", "event", "catalog", "search", "inventory"]
            if not any(kw in resp_url for kw in relevant_keywords):
                return

            data = response.json()

            def recursive_search(obj: Any, depth: int = 0) -> None:
                """Rekurencyjnie przeszukuje JSON w poszukiwaniu danych cenowych."""
                if depth > 8 or obj is None:
                    return

                if isinstance(obj, dict):
                    price, curr, name = extract_price_from_json(obj)

                    if price and price > 0:
                        # Zachowaj najniższą znalezioną cenę
                        if "floor_price" not in captured or price < captured["floor_price"]:
                            captured["floor_price"] = price
                            if curr:
                                captured["currency"] = curr

                    if name and "event_name" not in captured:
                        captured["event_name"] = name

                    for v in obj.values():
                        recursive_search(v, depth + 1)

                elif isinstance(obj, list):
                    for item in obj[:30]:  # Ogranicz głębokość iteracji
                        recursive_search(item, depth + 1)

            recursive_search(data)

        except Exception:
            pass  # Ignoruj błędy parsowania poszczególnych odpowiedzi

    with sync_playwright() as p:
        # Uruchom Chromium headless z ustawieniami anty-detekcji
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-web-security",
            ],
        )

        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        # Ukryj właściwości automatyzacji przeglądarki
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    { name: 'Chrome PDF Plugin' },
                    { name: 'Chrome PDF Viewer' },
                    { name: 'Native Client' },
                ]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };
        """)

        page = context.new_page()
        page.on("response", on_response)

        # Blokuj zbędne zasoby — przyspiesza ładowanie i redukuje timeouty.
        # Obrazki, fonty, reklamy nie są potrzebne do pobrania ceny.
        BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
        BLOCKED_DOMAINS = {
            "google-analytics.com", "doubleclick.net", "googlesyndication.com",
            "googletagmanager.com", "facebook.net", "twitter.com",
            "hotjar.com", "segment.com", "sentry.io", "nr-data.net",
        }

        def block_unnecessary(route):
            if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
                route.abort()
                return
            if any(d in route.request.url for d in BLOCKED_DOMAINS):
                route.abort()
                return
            route.continue_()

        page.route("**/*", block_unnecessary)

        try:
            logger.info(f"Ładowanie strony: {url}")
            # domcontentloaded: czeka tylko na HTML+JS, nie na obrazki/reklamy.
            # Dzięki temu unikamy timeoutów powodowanych przez zawieszające się
            # zasoby reklamowe Viagogo (które WAF czasem celowo blokuje botom).
            page.goto(url, wait_until="domcontentloaded", timeout=45000)

            # Poczekaj aż pojawi się element cenowy lub upłynie 15s
            try:
                page.wait_for_selector(
                    "[class*='Price'], [class*='price'], [itemprop='price'], button",
                    timeout=15000,
                )
            except Exception:
                pass  # Kontynuuj nawet jeśli selektor się nie pojawił

            page.wait_for_timeout(2000)  # Bufor na doładowanie danych JS

            # --- Sprawdź czy strona wymaga CAPTCHA ---
            try:
                body_text = page.inner_text("body").lower()
            except Exception:
                body_text = ""

            captcha_keywords = [
                "captcha", "robot check", "verify you are human",
                "recaptcha", "i am not a robot", "access denied",
            ]
            if any(kw in body_text for kw in captcha_keywords):
                logger.error("🚫 Wykryto CAPTCHA lub blokadę bota — scrapowanie niemożliwe")
                browser.close()
                return None

            # --- Fallback: Nazwa wydarzenia z tytułu strony ---
            if "event_name" not in captured:
                try:
                    title = page.title()
                    if title:
                        # Usuń suffix strony (np. "| viagogo" lub "– Buy Tickets")
                        clean = re.sub(r"\s*[|–-].*$", "", title).strip()
                        if clean:
                            captured["event_name"] = clean
                except Exception:
                    pass

            # --- Fallback: Meta tag og:title ---
            if "event_name" not in captured:
                try:
                    meta = page.query_selector("meta[property='og:title']")
                    if meta:
                        captured["event_name"] = meta.get_attribute("content")
                except Exception:
                    pass

            # --- Fallback: Dane LD+JSON (strukturalne dane w <script>) ---
            if "floor_price" not in captured:
                try:
                    ld_json_list = page.evaluate("""() => {
                        const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                        return Array.from(scripts).map(s => {
                            try { return JSON.parse(s.textContent); }
                            catch(e) { return null; }
                        }).filter(Boolean);
                    }""")

                    for item in (ld_json_list or []):
                        price, curr, name = extract_price_from_json(item)
                        if price and price > 0:
                            if "floor_price" not in captured or price < captured["floor_price"]:
                                captured["floor_price"] = price
                                if curr:
                                    captured["currency"] = curr
                        if name and "event_name" not in captured:
                            captured["event_name"] = name

                except Exception as e:
                    logger.debug(f"Błąd parsowania LD+JSON: {e}")

            # --- Fallback: Selektory CSS w DOM ---
            if "floor_price" not in captured:
                found_prices = []
                for selector in PRICE_CSS_SELECTORS:
                    try:
                        elements = page.query_selector_all(selector)
                        for el in elements:
                            text = el.inner_text()
                            price, curr = parse_price_from_text(text)
                            if price and price > 0:
                                found_prices.append((price, curr or "PLN"))
                    except Exception:
                        continue

                if found_prices:
                    # Wybierz najniższą znalezioną cenę
                    found_prices.sort(key=lambda x: x[0])
                    captured["floor_price"], captured["currency"] = found_prices[0]
                    logger.info(f"Cena znaleziona przez selektor CSS: {found_prices[0]}")

            # --- Fallback ostateczny: regex po całym tekście body ---
            # Viagogo może renderować ceny w elementach bez charakterystycznych klas
            if "floor_price" not in captured:
                try:
                    raw_body = page.inner_text("body").replace("\xa0", " ")
                    price_hits = re.findall(
                        rf"(?:{_MULTI_SYMBOL_RE})\s*[\d]{{1,6}}(?:[,.\s]\d{{3}})*"
                        rf"|[\d]{{1,6}}(?:[,.\s]\d{{3}})*\s*(?:{_MULTI_SYMBOL_RE})"
                        rf"|\b(?:{ISO_CURRENCY_CODES})\s+[\d]{{1,6}}(?:[,\s]\d{{3}})*",
                        raw_body,
                    )
                    body_prices = []
                    for hit in price_hits:
                        p, c = parse_price_from_text(hit)
                        if p and p > 0:
                            body_prices.append((p, c or "PLN"))
                    if body_prices:
                        body_prices.sort(key=lambda x: x[0])
                        captured["floor_price"], captured["currency"] = body_prices[0]
                        logger.info(f"Cena znaleziona przez regex body: {body_prices[0]}")
                except Exception as e:
                    logger.debug(f"Błąd skanowania body: {e}")

        except Exception as e:
            logger.error(f"Błąd podczas ładowania strony: {e}")
            browser.close()
            return None

        finally:
            browser.close()

    # Sprawdź czy w ogóle znaleziono cenę
    if "floor_price" not in captured:
        logger.warning("❌ Nie znaleziono ceny biletu na stronie")
        return None

    return {
        "event_name": captured.get("event_name", "Viagogo Event"),
        "floor_price": captured["floor_price"],
        "currency": captured.get("currency", "USD"),
    }


# =============================================================================
# Kursy walut — konwersja do wspólnej waluty (cache 1h)
# =============================================================================

_rate_cache: Dict[str, tuple] = {}

# Awaryjne kursy w przypadku braku dostępu do API
_FALLBACK_RATES: Dict[str, float] = {
    "EUR_PLN": 4.25, "USD_PLN": 3.90, "GBP_PLN": 4.95,
    "EUR_USD": 1.09, "PLN_EUR": 0.235, "PLN_USD": 0.256,
}


def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """
    Pobiera aktualny kurs wymiany walut z darmowego API (bez klucza API).

    Używa open.er-api.com. Wynik jest buforowany przez 1 godzinę.
    W razie błędu sieci zwraca przybliżony kurs awaryjny.
    """
    if from_currency == to_currency:
        return 1.0

    cache_key = f"{from_currency}_{to_currency}"
    now = time.time()

    if cache_key in _rate_cache:
        rate, ts = _rate_cache[cache_key]
        if now - ts < 3600:
            return rate

    try:
        url = f"https://open.er-api.com/v6/latest/{from_currency}"
        with urllib.request.urlopen(url, timeout=6) as resp:  # type: ignore
            data = json.loads(resp.read())
        rate = float(data["rates"][to_currency])
        _rate_cache[cache_key] = (rate, now)
        logger.info(f"Kurs {from_currency}/{to_currency}: {rate:.4f}")
        return rate
    except Exception as e:
        logger.debug(f"Błąd pobierania kursu {from_currency}/{to_currency}: {e}")
        fallback = _FALLBACK_RATES.get(cache_key, 1.0)
        logger.warning(f"Używam awaryjnego kursu {from_currency}/{to_currency}: {fallback}")
        return fallback


# =============================================================================
# Scraper — Ticombo
# =============================================================================


def scrape_ticombo(url: str) -> Optional[Dict[str, Any]]:
    """
    Scrapuje stronę Ticombo i zwraca najniższą dostępną cenę biletu.

    Strategia wymuszenia PLN:
      - Route intercept: zamienia `currency=EUR` → `currency=PLN` w URL
        żądań do API Ticombo (endpointy /discovery/search/*)
      - Dzięki temu API zwraca ceny bezpośrednio w PLN — brak potrzeby
        przeliczania kursów walut i możliwość bezpośredniego porównania
        z cenami Viagogo

    Fallback ekstrakcji (gdy API nie zwróci ceny):
      1. Selektory CSS [class*='price']
      2. Regex po całym tekście body

    Zwraca:
      {"event_name": str, "floor_price": float, "currency": str}
      lub None gdy nie udało się pobrać ceny.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("❌ Playwright nie jest zainstalowany")
        return None

    delay = random.uniform(3, 8)
    logger.info(f"Ticombo: oczekiwanie {delay:.1f}s (anty-bot)...")
    time.sleep(delay)

    captured: Dict[str, Any] = {}

    def on_response(response) -> None:
        """Przechwytuje odpowiedzi JSON z API Ticombo."""
        try:
            if response.status != 200:
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            resp_url = response.url
            # Interesują nas endpointy discovery — zawierają dane o biletach
            if "/discovery/" not in resp_url:
                return

            data = response.json()
            # Waluta z URL (po modyfikacji route → powinno być PLN)
            url_currency = "PLN" if "currency=PLN" in resp_url else (
                "EUR" if "currency=EUR" in resp_url else None
            )

            def search_tc(obj: Any, depth: int = 0) -> None:
                if depth > 8 or obj is None:
                    return
                if isinstance(obj, dict):
                    # Klucze cenowe używane przez Ticombo API
                    for price_key in ("price", "minPrice", "fromPrice", "startingPrice"):
                        val = obj.get(price_key)
                        if isinstance(val, (int, float)) and val > 0:
                            if "floor_price" not in captured or val < captured["floor_price"]:
                                captured["floor_price"] = float(val)
                                if url_currency:
                                    captured["currency"] = url_currency
                    # Nazwa wydarzenia
                    for name_key in ("name", "eventName", "title"):
                        val = obj.get(name_key)
                        if isinstance(val, str) and "world cup" in val.lower():
                            if "event_name" not in captured:
                                captured["event_name"] = val
                            break
                    for v in obj.values():
                        search_tc(v, depth + 1)
                elif isinstance(obj, list):
                    for item in obj[:20]:
                        search_tc(item, depth + 1)

            search_tc(data)
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        page = context.new_page()
        page.on("response", on_response)

        BLOCKED_TYPES = {"image", "media", "font", "stylesheet"}
        BLOCKED_DOMAINS = {
            "google-analytics.com", "doubleclick.net", "googlesyndication.com",
            "googletagmanager.com", "facebook.net", "hotjar.com",
            "segment.com", "sentry.io", "nr-data.net",
        }

        def route_handler(route) -> None:
            req = route.request
            # Blokuj zbędne zasoby
            if req.resource_type in BLOCKED_TYPES:
                route.abort(); return
            if any(d in req.url for d in BLOCKED_DOMAINS):
                route.abort(); return
            # Podmień currency=EUR → currency=PLN w zapytaniach do API Ticombo
            # Dzięki temu API zwraca ceny w PLN bez przeliczania kursów
            if "/discovery/" in req.url and "currency=EUR" in req.url:
                route.continue_(url=req.url.replace("currency=EUR", "currency=PLN"))
                return
            route.continue_()

        page.route("**/*", route_handler)

        try:
            logger.info(f"Ticombo: ładowanie strony {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector("[class*='price'],[class*='Price']", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            # Sprawdź CAPTCHA
            try:
                body_text = page.inner_text("body").lower()
            except Exception:
                body_text = ""

            if any(kw in body_text for kw in ["captcha", "verify you are human", "access denied"]):
                logger.error("Ticombo: 🚫 Wykryto CAPTCHA")
                browser.close()
                return None

            # Fallback: nazwa z tytułu strony
            if "event_name" not in captured:
                try:
                    title = page.title()
                    if title:
                        clean = re.sub(r"\s*[-–|].*$", "", title).strip()
                        if len(clean) > 3:
                            captured["event_name"] = clean
                except Exception:
                    pass

            # Fallback DOM: selektory cenowe
            if "floor_price" not in captured:
                for sel in ["[class*='price']", "[class*='Price']", "[data-price]"]:
                    try:
                        els = page.query_selector_all(sel)
                        dom_prices = []
                        for el in els:
                            p, c = parse_price_from_text(el.inner_text())
                            if p and p > 0:
                                dom_prices.append((p, c or "EUR"))
                        if dom_prices:
                            dom_prices.sort(key=lambda x: x[0])
                            captured["floor_price"], captured["currency"] = dom_prices[0]
                            logger.info(f"Ticombo: cena z DOM {dom_prices[0]}")
                            break
                    except Exception:
                        continue

            # Fallback body regex
            if "floor_price" not in captured:
                try:
                    raw = page.inner_text("body").replace("\xa0", " ")
                    hits = re.findall(
                        rf"(?:{_MULTI_SYMBOL_RE})\s*[\d]{{1,6}}(?:[,.\s]\d{{3}})*"
                        rf"|[\d]{{1,6}}(?:[,.\s]\d{{3}})*\s*(?:{_MULTI_SYMBOL_RE})"
                        rf"|\b(?:{ISO_CURRENCY_CODES})\s+[\d]{{1,6}}(?:[,\s]\d{{3}})*",
                        raw,
                    )
                    body_prices = [(p, c or "EUR") for h in hits
                                   for p, c in [parse_price_from_text(h)] if p and p > 0]
                    if body_prices:
                        body_prices.sort(key=lambda x: x[0])
                        captured["floor_price"], captured["currency"] = body_prices[0]
                        logger.info(f"Ticombo: cena z body regex {body_prices[0]}")
                except Exception as e:
                    logger.debug(f"Ticombo: błąd skanowania body: {e}")

        except Exception as e:
            logger.error(f"Ticombo: błąd podczas ładowania: {e}")
            browser.close()
            return None

        finally:
            browser.close()

    if "floor_price" not in captured:
        logger.warning("Ticombo: ❌ Nie znaleziono ceny biletu")
        return None

    return {
        "event_name": captured.get("event_name", "World Cup Final"),
        "floor_price": captured["floor_price"],
        "currency": captured.get("currency", "EUR"),
    }


# =============================================================================
# Orkiestrator pojedynczego pobrania
# =============================================================================


def _scrape_with_retries(
    scrape_fn,
    url: str,
    platform_name: str,
) -> Optional[Dict[str, Any]]:
    """
    Wywołuje podany scraper z automatycznym ponawianiem przy błędach.
    Zwraca wynik lub None po wyczerpaniu prób.
    """
    result = None
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            logger.info(f"{platform_name}: próba {attempt}/{MAX_RETRIES}...")
        result = scrape_fn(url)
        if result:
            return result
        if attempt < MAX_RETRIES:
            logger.warning(
                f"{platform_name}: ⏳ próba {attempt} nieudana, "
                f"ponawiam za {RETRY_DELAY_SECONDS // 60} min..."
            )
            time.sleep(RETRY_DELAY_SECONDS)
    return None


def load_events() -> dict:
    """Laduje konfiguracje z events.json."""
    try:
        with open(EVENTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Blad ladowania {EVENTS_FILE}: {e}")
        return {"settings": {}, "affiliate": {}, "events": []}


def _scrape_with_retries(scrape_fn, url, platform_name):
    """Wywoluje scraper z automatycznym ponawianiem przy bledach."""
    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            logger.info(f"{platform_name}: proba {attempt}/{MAX_RETRIES}...")
        result = scrape_fn(url)
        if result:
            return result
        if attempt < MAX_RETRIES:
            logger.warning(
                f"{platform_name}: proba {attempt} nieudana, "
                f"ponawiam za {RETRY_DELAY_SECONDS // 60} min..."
            )
            time.sleep(RETRY_DELAY_SECONDS)
    return None


def run_event(event):
    """Scrapuje wszystkie platformy dla jednego wydarzenia i zapisuje do DB."""
    eid = event["id"]
    name = event["name"]
    urls = event.get("urls", {})
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"--- {name} ({eid}) ---")

    scrapers = [
        ("Viagogo", scrape_viagogo, urls.get("viagogo", "")),
        ("StubHub", scrape_viagogo, urls.get("stubhub", "")),  # StubHub uzywa tego samego scrapera
        ("Ticombo", scrape_ticombo, urls.get("ticombo", "")),
    ]

    results = {}
    for platform, fn, url in scrapers:
        if not url or url.startswith(_PLACEHOLDER):
            logger.info(f"{platform}: brak URL -- pomijam")
            continue
        logger.info(f"Scrapuje {platform}...")
        result = _scrape_with_retries(fn, url, platform)
        if result:
            save_to_db(timestamp, eid, name, platform, result["floor_price"], result["currency"])
            save_to_csv(
                timestamp=timestamp,
                event_name=name,
                floor_price=result["floor_price"],
                currency=result["currency"],
                platform=platform,
                csv_file=VIAGOGO_CSV if platform == "Viagogo" else TICOMBO_CSV,
            )
            results[platform] = result
            logger.info(f"{platform}: {result['floor_price']} {result['currency']}")
        else:
            logger.error(f"{platform}: brak ceny po wszystkich probach")

    if results:
        cheapest = min(results, key=lambda p: results[p]["floor_price"])
        r = results[cheapest]
        logger.info(f"Najtaniej: {cheapest} {r['floor_price']} {r['currency']}")

    return results


def run_scraper():
    """Wykonuje jedno pelne pobranie dla wszystkich aktywnych wydarzen."""
    logger.info("=" * 55)
    config = load_events()
    events = [e for e in config.get("events", []) if e.get("active", True)]

    if not events:
        # Fallback na legacy tryb jednego wydarzenia
        logger.info("Brak wydarzen w events.json -- tryb legacy")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        v_result = _scrape_with_retries(scrape_viagogo, EVENT_URL, "Viagogo")
        if v_result:
            save_to_csv(timestamp=timestamp, event_name=v_result["event_name"],
                        floor_price=v_result["floor_price"], currency=v_result["currency"],
                        platform="Viagogo", csv_file=VIAGOGO_CSV)
        t_result = _scrape_with_retries(scrape_ticombo, TICOMBO_URL, "Ticombo")
        if t_result:
            save_to_csv(timestamp=timestamp, event_name=t_result["event_name"],
                        floor_price=t_result["floor_price"], currency=t_result["currency"],
                        platform="Ticombo", csv_file=TICOMBO_CSV)
        if v_result:
            try:
                from plot import generate_chart
                generate_chart(csv_file=VIAGOGO_CSV, chart_file=CHART_FILE)
            except Exception as e:
                logger.warning(f"Nie mozna wygenerowac wykresu: {e}")
        return

    logger.info(f"Pobieranie cen dla {len(events)} wydarzen...")
    for event in events:
        run_event(event)

    # Generuj wykresy + raport HTML
    try:
        from report import generate_reports
        path = generate_reports(EVENTS_FILE, DB_FILE, REPORTS_DIR)
        if path:
            logger.info(f"Raport HTML: {path}")
    except Exception as e:
        logger.warning(f"Nie mozna wygenerowac raportu: {e}")


# =============================================================================
# Punkt wejscia
# =============================================================================


def main():
    """Uruchamia tracker z harmonogramem."""
    import schedule

    config = load_events()
    settings = config.get("settings", {})
    interval = settings.get("interval_minutes", INTERVAL_MINUTES)
    events = config.get("events", [])
    active = [e for e in events if e.get("active", True)]

    logger.info("Ticket Price Tracker -- start")
    if active:
        for e in active:
            logger.info(f"  Wydarzenie: {e['name']} ({e['date']})")
    else:
        logger.info(f"  Legacy tryb: Viagogo URL: {EVENT_URL}")
    logger.info(f"Interwal: co {interval} minut")
    logger.info("Zatrzymaj skrypt: Ctrl+C")
    logger.info("=" * 55)

    run_scraper()

    schedule.every(interval).minutes.do(run_scraper)
    logger.info(f"Harmonogram aktywny. Nastepne pobranie za {interval} minut.")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Tracker zatrzymany (Ctrl+C)")
        sys.exit(0)


if __name__ == "__main__":
    main()
