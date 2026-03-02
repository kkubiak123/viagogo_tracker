#!/usr/bin/env bash
# =============================================================================
# setup.sh — Instalacja Viagogo Price Tracker na macOS
# Uruchomienie: bash setup.sh
# =============================================================================

set -e  # Zatrzymaj skrypt przy pierwszym błędzie

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   Viagogo Price Tracker — Instalacja macOS   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# =============================================================================
# 1. Sprawdź i zainstaluj Homebrew
# =============================================================================
echo "🔍 Sprawdzam Homebrew..."

if ! command -v brew &>/dev/null; then
    echo "📦 Homebrew nie znaleziony — instaluję..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Dodaj Homebrew do PATH dla Apple Silicon (M1/M2/M3)
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
else
    echo "✅ Homebrew jest już zainstalowany ($(brew --version | head -1))"
fi

# =============================================================================
# 2. Zainstaluj Python 3.11
# =============================================================================
echo ""
echo "🐍 Sprawdzam Python 3.11..."

if ! brew list python@3.11 &>/dev/null; then
    echo "📥 Instaluję Python 3.11..."
    brew install python@3.11
else
    echo "✅ Python 3.11 jest już zainstalowany"
fi

# Ustal ścieżkę do python3.11
PYTHON_BIN="$(brew --prefix python@3.11)/bin/python3.11"
echo "   Używam: $PYTHON_BIN ($(${PYTHON_BIN} --version))"

# =============================================================================
# 3. Utwórz wirtualne środowisko Python
# =============================================================================
echo ""
echo "🔧 Tworzę wirtualne środowisko Python (venv)..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"

if [[ -d "$VENV_DIR" ]]; then
    echo "ℹ️  Katalog venv już istnieje — pomijam tworzenie"
else
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    echo "✅ Środowisko wirtualne utworzone: $VENV_DIR"
fi

# =============================================================================
# 4. Aktywuj venv i zainstaluj zależności
# =============================================================================
echo ""
echo "📚 Instaluję zależności Python..."

source "${VENV_DIR}/bin/activate"

pip install --upgrade pip --quiet
pip install playwright schedule matplotlib pandas pytest

echo "✅ Zainstalowane pakiety:"
pip show playwright schedule matplotlib pandas pytest | grep -E "^(Name|Version):" | paste - -

# =============================================================================
# 5. Pobierz przeglądarkę Chromium dla Playwright
# =============================================================================
echo ""
echo "🌐 Pobieranie Chromium dla Playwright..."
playwright install chromium
echo "✅ Chromium zainstalowany"

# =============================================================================
# Podsumowanie
# =============================================================================
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║        ✅ Instalacja zakończona!             ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Jak uruchomić tracker:"
echo ""
echo "  1. Aktywuj środowisko wirtualne:"
echo "     source venv/bin/activate"
echo ""
echo "  2. Uruchom tracker (pobiera ceny co 60 minut):"
echo "     python tracker.py"
echo ""
echo "  3. Wygeneruj wykres ręcznie:"
echo "     python plot.py"
echo ""
echo "  4. Uruchom testy:"
echo "     pytest test_tracker.py -v"
echo ""
