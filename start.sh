#!/usr/bin/env bash
# Lance le serveur MoodLamp et ouvre la page dans le navigateur.
#
# Usage : ./start.sh
# Arrêt : Ctrl+C dans le terminal

cd "$(dirname "$0")"

# Ouvre le navigateur après 2 sec (le temps que le serveur démarre)
( sleep 2 && open "http://127.0.0.1:8765" ) &

# Lance le serveur (bloque le terminal jusqu'à Ctrl+C)
PYTHONPATH=. python3 -m moodlamp.server
