#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Testy jednostkowe — Viagogo Price Tracker
============================================================
Uruchomienie:
    pytest test_tracker.py -v

Testy NIE wymagają dostępu do internetu ani uruchomionej przeglądarki.
Wszystkie operacje sieciowe są zastąpione mockami lub danymi testowymi.
"""

import csv
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Dodaj katalog projektu do ścieżki — umożliwia import tracker i plot
sys.path.insert(0, str(Path(__file__).parent))

from tracker import (
    parse_price_from_text,
    parse_price_from_html,
    extract_price_from_json,
    save_to_csv,
)


# =============================================================================
# Test 1: Parsowanie ceny z tekstu / HTML
# =============================================================================

class TestParsePriceFromText:
    """
    Sprawdza czy parse_price_from_text() poprawnie wyciąga
    wartość liczbową i walutę z różnych formatów tekstowych.
    """

    def test_euro_symbol_prefix(self):
        """€245 → (245.0, 'EUR')"""
        price, currency = parse_price_from_text("€245")
        assert price == 245.0
        assert currency == "EUR"

    def test_dollar_symbol_prefix(self):
        """$350 → (350.0, 'USD')"""
        price, currency = parse_price_from_text("$350")
        assert price == 350.0
        assert currency == "USD"

    def test_pound_symbol_prefix(self):
        """£199 → (199.0, 'GBP')"""
        price, currency = parse_price_from_text("£199")
        assert price == 199.0
        assert currency == "GBP"

    def test_from_prefix_ignored(self):
        """'From €245' → (245.0, 'EUR') — słowo From jest ignorowane"""
        price, currency = parse_price_from_text("From €245")
        assert price == 245.0
        assert currency == "EUR"

    def test_iso_code_after_number(self):
        """'245 EUR' → (245.0, 'EUR')"""
        price, currency = parse_price_from_text("245 EUR")
        assert price == 245.0
        assert currency == "EUR"

    def test_iso_code_before_number(self):
        """'USD 499' → (499.0, 'USD')"""
        price, currency = parse_price_from_text("USD 499")
        assert price == 499.0
        assert currency == "USD"

    def test_price_with_decimals(self):
        """€245.50 → (245.5, 'EUR')"""
        price, currency = parse_price_from_text("€245.50")
        assert price == pytest.approx(245.50)
        assert currency == "EUR"

    def test_price_with_comma_thousands(self):
        """€1,234 → (1234.0, 'EUR')"""
        price, currency = parse_price_from_text("€1,234")
        assert price == 1234.0
        assert currency == "EUR"

    def test_sentence_context(self):
        """'Tickets from €245 per person' → (245.0, 'EUR')"""
        price, currency = parse_price_from_text("Tickets from €245 per person")
        assert price == 245.0
        assert currency == "EUR"

    def test_empty_string_returns_none(self):
        """Pusty string → (None, None)"""
        price, currency = parse_price_from_text("")
        assert price is None
        assert currency is None

    def test_none_input_returns_none(self):
        """None jako wejście → (None, None)"""
        price, currency = parse_price_from_text(None)
        assert price is None
        assert currency is None

    def test_text_without_price_returns_none(self):
        """Tekst bez ceny → (None, None)"""
        price, currency = parse_price_from_text("No tickets available right now")
        assert price is None
        assert currency is None

    def test_whitespace_only_returns_none(self):
        """Tylko białe znaki → (None, None)"""
        price, currency = parse_price_from_text("   \t  ")
        assert price is None
        assert currency is None


class TestParsePriceFromHtml:
    """
    Sprawdza parse_price_from_html() na przykładowych fragmentach HTML.
    Symuluje dane pobierane z DOM strony Viagogo.
    """

    def test_html_span_with_price(self):
        """<span class='price'>€245</span> → (245.0, 'EUR')"""
        html = '<span class="price">€245</span>'
        price, currency = parse_price_from_html(html)
        assert price == 245.0
        assert currency == "EUR"

    def test_html_from_price_element(self):
        """Typowy element 'from price' z Viagogo → poprawna cena"""
        html = '<p class="FromPrice__amount">From <strong>€312</strong></p>'
        price, currency = parse_price_from_html(html)
        assert price == 312.0
        assert currency == "EUR"

    def test_html_with_nested_tags(self):
        """Zagnieżdżone tagi HTML → cena wyciągnięta z tekstu"""
        html = '<div class="ticket-price"><span>$</span><span>189</span></div>'
        price, currency = parse_price_from_html(html)
        assert price == 189.0
        assert currency == "USD"

    def test_empty_html_returns_none(self):
        """Pusty HTML → (None, None)"""
        price, currency = parse_price_from_html("")
        assert price is None
        assert currency is None

    def test_html_without_price_returns_none(self):
        """HTML bez ceny → (None, None)"""
        html = '<div class="no-tickets">Sold out</div>'
        price, currency = parse_price_from_html(html)
        assert price is None
        assert currency is None


# =============================================================================
# Test 2: Zapis do CSV — tworzenie pliku z nagłówkami
# =============================================================================

class TestSaveToCSVCreation:
    """Sprawdza czy save_to_csv() tworzy plik CSV z poprawnymi nagłówkami."""

    def test_creates_file_on_first_call(self, tmp_path):
        """Plik CSV nie istnieje → zostaje utworzony."""
        csv_path = str(tmp_path / "prices.csv")
        save_to_csv("2025-06-01 14:00:00", "FIFA World Cup", 245.0, "EUR", "Viagogo", csv_path)
        assert Path(csv_path).exists()

    def test_creates_correct_headers(self, tmp_path):
        """Nagłówki CSV: timestamp, event_name, floor_price, currency, platform."""
        csv_path = str(tmp_path / "prices.csv")
        save_to_csv("2025-06-01 14:00:00", "FIFA World Cup", 245.0, "EUR", "Viagogo", csv_path)

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert reader.fieldnames == [
            "timestamp", "event_name", "floor_price", "currency", "platform"
        ]

    def test_correct_data_in_row(self, tmp_path):
        """Zapisane wartości zgadzają się z danymi wejściowymi."""
        csv_path = str(tmp_path / "prices.csv")
        save_to_csv("2025-06-01 14:00:00", "FIFA World Cup", 245.0, "EUR", "Viagogo", csv_path)

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2025-06-01 14:00:00"
        assert rows[0]["event_name"] == "FIFA World Cup"
        assert float(rows[0]["floor_price"]) == 245.0
        assert rows[0]["currency"] == "EUR"
        assert rows[0]["platform"] == "Viagogo"

    def test_platform_field_default_empty(self, tmp_path):
        """Pole platform ma domyślną wartość pustego stringa."""
        csv_path = str(tmp_path / "prices.csv")
        save_to_csv("2025-06-01 14:00:00", "Event", 100.0, "EUR", csv_file=csv_path)
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["platform"] == ""

    def test_returns_true_on_success(self, tmp_path):
        """Funkcja zwraca True przy udanym zapisie."""
        csv_path = str(tmp_path / "prices.csv")
        result = save_to_csv("2025-06-01 14:00:00", "Event", 100.0, "EUR", csv_file=csv_path)
        assert result is True


# =============================================================================
# Test 3: Dopisywanie wierszy (nie nadpisywanie)
# =============================================================================

class TestSaveToCSVAppend:
    """Sprawdza czy kolejne wywołania dopisują wiersze bez nadpisywania."""

    def test_three_calls_produce_three_rows(self, tmp_path):
        """3 wywołania → 3 wiersze danych w CSV."""
        csv_path = str(tmp_path / "prices.csv")

        save_to_csv("2025-06-01 10:00:00", "World Cup", 200.0, "EUR", "Viagogo", csv_path)
        save_to_csv("2025-06-01 11:00:00", "World Cup", 190.0, "EUR", "Ticombo", csv_path)
        save_to_csv("2025-06-01 12:00:00", "World Cup", 210.0, "EUR", "Viagogo", csv_path)

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3

    def test_rows_preserve_order(self, tmp_path):
        """Kolejność wierszy jest zachowana (chronologiczna)."""
        csv_path = str(tmp_path / "prices.csv")

        save_to_csv("2025-06-01 10:00:00", "World Cup", 200.0, "EUR", "Viagogo", csv_path)
        save_to_csv("2025-06-01 11:00:00", "World Cup", 190.0, "EUR", "Ticombo", csv_path)
        save_to_csv("2025-06-01 12:00:00", "World Cup", 210.0, "EUR", "Viagogo", csv_path)

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert float(rows[0]["floor_price"]) == 200.0
        assert float(rows[1]["floor_price"]) == 190.0
        assert float(rows[2]["floor_price"]) == 210.0

    def test_headers_appear_exactly_once(self, tmp_path):
        """Nagłówki są w pliku dokładnie jeden raz — nie powtarzają się."""
        csv_path = str(tmp_path / "prices.csv")

        save_to_csv("2025-06-01 10:00:00", "Event", 100.0, "EUR", "Viagogo", csv_path)
        save_to_csv("2025-06-01 11:00:00", "Event", 110.0, "EUR", "Ticombo", csv_path)
        save_to_csv("2025-06-01 12:00:00", "Event", 120.0, "EUR", "Viagogo", csv_path)

        content = Path(csv_path).read_text(encoding="utf-8")
        assert content.count("timestamp") == 1
        assert content.count("floor_price") == 1

    def test_different_events_can_coexist(self, tmp_path):
        """Różne nazwy wydarzeń mogą być w tym samym pliku CSV."""
        csv_path = str(tmp_path / "prices.csv")

        save_to_csv("2025-06-01 10:00:00", "World Cup", 200.0, "EUR", "Viagogo", csv_path)
        save_to_csv("2025-06-01 11:00:00", "Euro 2024", 150.0, "USD", "Ticombo", csv_path)

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["event_name"] == "World Cup"
        assert rows[1]["event_name"] == "Euro 2024"


# =============================================================================
# Test 4: Generowanie wykresu
# =============================================================================

class TestGenerateChart:
    """Sprawdza czy generate_chart() poprawnie tworzy plik chart.png."""

    def _write_sample_csv(self, path: str, rows: int = 3) -> None:
        """Pomocnicza metoda tworząca przykładowy plik CSV z danymi Viagogo."""
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp", "event_name", "floor_price", "currency", "platform"]
            )
            writer.writeheader()
            for i in range(rows):
                writer.writerow(
                    {
                        "timestamp": f"2025-06-0{i + 1} 10:00:00",
                        "event_name": "FIFA World Cup",
                        "floor_price": 30000 + i * 500,
                        "currency": "PLN",
                        "platform": "Viagogo",
                    }
                )

    def test_chart_file_is_created(self, tmp_path):
        """Po wywołaniu generate_chart() plik PNG musi istnieć."""
        from plot import generate_chart

        csv_path = str(tmp_path / "prices.csv")
        chart_path = str(tmp_path / "chart.png")
        self._write_sample_csv(csv_path, rows=3)

        result = generate_chart(csv_file=csv_path, chart_file=chart_path)

        assert result is True
        assert Path(chart_path).exists()

    def test_chart_file_is_not_empty(self, tmp_path):
        """Plik PNG ma niezerowy rozmiar (jest prawdziwym obrazem)."""
        from plot import generate_chart

        csv_path = str(tmp_path / "prices.csv")
        chart_path = str(tmp_path / "chart.png")
        self._write_sample_csv(csv_path, rows=4)

        generate_chart(csv_file=csv_path, chart_file=chart_path)

        assert Path(chart_path).stat().st_size > 1000  # minimum 1 KB

    def test_returns_false_for_missing_csv(self, tmp_path):
        """Zwraca False gdy plik CSV nie istnieje — nie rzuca wyjątku."""
        from plot import generate_chart

        csv_path = str(tmp_path / "nonexistent.csv")
        chart_path = str(tmp_path / "chart.png")

        result = generate_chart(csv_file=csv_path, chart_file=chart_path)

        assert result is False
        assert not Path(chart_path).exists()

    def test_returns_false_for_single_row(self, tmp_path):
        """Zwraca False gdy CSV ma tylko 1 wpis (za mało do wykresu liniowego)."""
        from plot import generate_chart

        csv_path = str(tmp_path / "prices.csv")
        chart_path = str(tmp_path / "chart.png")
        self._write_sample_csv(csv_path, rows=1)

        result = generate_chart(csv_file=csv_path, chart_file=chart_path)

        assert result is False

    def test_returns_false_for_empty_csv(self, tmp_path):
        """Zwraca False gdy CSV ma tylko nagłówki (0 wierszy danych)."""
        from plot import generate_chart

        csv_path = str(tmp_path / "prices.csv")
        chart_path = str(tmp_path / "chart.png")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["timestamp", "event_name", "floor_price", "currency", "platform"]
            )
            writer.writeheader()

        result = generate_chart(csv_file=csv_path, chart_file=chart_path)
        assert result is False

    def test_chart_uses_viagogo_file(self, tmp_path):
        """Wykres generowany jest z dedykowanego pliku Viagogo (viagogo_prices.csv)."""
        from plot import generate_chart

        csv_path = str(tmp_path / "viagogo_prices.csv")
        chart_path = str(tmp_path / "chart.png")
        self._write_sample_csv(csv_path, rows=3)

        result = generate_chart(csv_file=csv_path, chart_file=chart_path)

        assert result is True
        assert Path(chart_path).exists()
        assert Path(chart_path).stat().st_size > 1000


# =============================================================================
# Test 5: Obsługa błędów — brak ceny / błędne dane
# =============================================================================

class TestErrorHandling:
    """
    Sprawdza czy brak ceny lub błędne dane nie powodują wyjątków.
    Funkcje powinny logować błąd i zwracać bezpieczną wartość.
    """

    def test_parse_empty_string_no_exception(self):
        """Pusty string nie powoduje wyjątku."""
        try:
            result = parse_price_from_text("")
        except Exception as e:
            pytest.fail(f"parse_price_from_text('') rzuciło wyjątek: {e}")
        assert result == (None, None)

    def test_parse_none_no_exception(self):
        """None nie powoduje wyjątku."""
        try:
            result = parse_price_from_text(None)
        except Exception as e:
            pytest.fail(f"parse_price_from_text(None) rzuciło wyjątek: {e}")
        assert result == (None, None)

    def test_parse_captcha_page_no_exception(self):
        """Tekst ze strony CAPTCHA nie powoduje wyjątku."""
        captcha_texts = [
            "Please verify you are human",
            "Robot check required",
            "CAPTCHA challenge — click below",
            "Access denied. Please complete the security check.",
        ]
        for text in captcha_texts:
            try:
                price, currency = parse_price_from_text(text)
            except Exception as e:
                pytest.fail(f"parse_price_from_text({repr(text)}) rzuciło wyjątek: {e}")
            assert price is None, f"Nieoczekiwana cena dla tekstu CAPTCHA: {text}"

    def test_parse_random_garbage_no_exception(self):
        """Losowe znaki specjalne nie powodują wyjątku."""
        garbage_inputs = [
            "!!!###@@@",
            "\x00\x01\x02",
            "a" * 10000,
            "123 abc xyz 456",
        ]
        for text in garbage_inputs:
            try:
                parse_price_from_text(text)
            except Exception as e:
                pytest.fail(f"parse_price_from_text rzuciło wyjątek dla {repr(text[:50])}: {e}")

    def test_save_to_csv_invalid_path_no_exception(self, tmp_path):
        """Zapis do nieistniejącego katalogu nie powoduje nieobsługiwanego wyjątku."""
        invalid_path = str(tmp_path / "nonexistent_dir" / "prices.csv")
        try:
            result = save_to_csv(
                timestamp="2025-06-01 10:00:00",
                event_name="Test Event",
                floor_price=100.0,
                currency="EUR",
                platform="Test",
                csv_file=invalid_path,
            )
            # Funkcja powinna zwrócić False — nie rzucać wyjątku
            assert result is False
        except Exception as e:
            pytest.fail(
                f"save_to_csv z nieprawidłową ścieżką rzuciło nieobsługiwany wyjątek: {e}"
            )

    def test_extract_price_from_json_empty_dict(self):
        """Pusty słownik JSON → (None, None, None) bez wyjątku."""
        try:
            price, currency, name = extract_price_from_json({})
        except Exception as e:
            pytest.fail(f"extract_price_from_json({{}}) rzuciło wyjątek: {e}")
        assert price is None
        assert currency is None
        assert name is None

    def test_extract_price_from_json_non_dict(self):
        """Nie-słownik (np. lista, None, int) → (None, None, None) bez wyjątku."""
        for bad_input in [None, [], "string", 42, True]:
            try:
                price, currency, name = extract_price_from_json(bad_input)
            except Exception as e:
                pytest.fail(
                    f"extract_price_from_json({repr(bad_input)}) rzuciło wyjątek: {e}"
                )
            assert price is None

    def test_extract_price_from_json_with_valid_data(self):
        """Poprawny JSON z ceną → zwraca właściwe wartości."""
        data = {
            "name": "FIFA World Cup Final",
            "minPrice": {"amount": 299.0, "currency": "EUR"},
        }
        price, currency, name = extract_price_from_json(data)
        assert price == 299.0
        assert currency == "EUR"
        assert name == "FIFA World Cup Final"

    def test_extract_price_from_json_flat_price(self):
        """JSON z ceną jako liczba bezpośrednio pod kluczem → poprawny wynik."""
        data = {"floorPrice": 150.0, "currency": "USD"}
        price, currency, name = extract_price_from_json(data)
        assert price == 150.0
        assert currency == "USD"
