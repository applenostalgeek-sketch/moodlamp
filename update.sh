#!/usr/bin/env bash
# Lance le calcul du score et ouvre le HTML.
#
# Usage :
#   ./update.sh           → utilise le cache (instantané)
#   ./update.sh --refresh → re-parse l'XML (après nouvel export Apple Santé, ~30s)
#   ./update.sh --at "2026-04-25 09:00"  → score à une date passée

cd "$(dirname "$0")"
PYTHONPATH=. python3 tools/score_to_html.py "$@"
