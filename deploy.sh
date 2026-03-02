#!/usr/bin/env bash
# deploy.sh — publikuje stronę TicketWay na GitHub Pages
#
# Jak działa:
#   1. Generuje raport HTML z aktualnymi cenami
#   2. Kopiuje pliki do gałęzi "gh-pages" (odizolowanej od kodu)
#   3. Pushuje na GitHub → strona live pod adresem poniżej
#
# Pierwsze uruchomienie:
#   chmod +x deploy.sh && ./deploy.sh
#
# Strona będzie dostępna pod:
#   https://kkubiak123.github.io/viagogo_tracker/
#
# Automatyczne odświeżanie co godzinę — dodaj do crontab (crontab -e):
#   0 * * * * cd /Users/kacperkubiak/Desktop/Antrop/viagogo_tracker && python3 tracker.py --once && ./deploy.sh >> deploy.log 2>&1

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORTS_DIR="$REPO_DIR/reports"
DEPLOY_BRANCH="gh-pages"
CURRENT_BRANCH="main"

cd "$REPO_DIR"

echo "[TicketWay deploy] Generowanie raportu..."
python3 -c "from report import generate_index; generate_index()" 2>&1 | grep -v "^\[" || true

if [ ! -f "$REPORTS_DIR/index.html" ]; then
    echo "Błąd: reports/index.html nie istnieje. Sprawdź czy tracker zebrał dane."
    exit 1
fi

# Zapisz pliki do tymczasowego katalogu (przed zmianą gałęzi)
TEMP=$(mktemp -d)
cp "$REPORTS_DIR/index.html" "$TEMP/index.html"
mkdir -p "$TEMP/charts"
cp "$REPORTS_DIR/charts/"*.png "$TEMP/charts/" 2>/dev/null || true

echo "[TicketWay deploy] Przygotowanie gałęzi $DEPLOY_BRANCH..."

# Sprawdź czy gałąź gh-pages już istnieje
if git show-ref --quiet refs/heads/$DEPLOY_BRANCH; then
    git checkout $DEPLOY_BRANCH
else
    # Pierwsza publikacja — utwórz orphan branch (bez historii)
    git checkout --orphan $DEPLOY_BRANCH
    git rm -rf . --quiet 2>/dev/null || true
fi

# Wyczyść stare pliki statyczne (zachowaj .nojekyll)
rm -f index.html
rm -rf charts/

# Skopiuj nowe pliki z temp
cp "$TEMP/index.html" index.html
mkdir -p charts
cp "$TEMP/charts/"*.png charts/ 2>/dev/null || true
rm -rf "$TEMP"

# GitHub Pages nie uruchamia Jekyll (szybsze, brak problemów z _ w nazwach)
touch .nojekyll

git add index.html charts/ .nojekyll
git commit -m "deploy: $(date '+%Y-%m-%d %H:%M')" --allow-empty

echo "[TicketWay deploy] Pushowanie na GitHub..."
git push origin $DEPLOY_BRANCH

# Wróć do gałęzi roboczej
git checkout $CURRENT_BRANCH

echo ""
echo "✅ Strona opublikowana!"
echo "   URL: https://kkubiak123.github.io/viagogo_tracker/"
echo "   (pierwsze uruchomienie może potrwać 2-3 minuty)"
