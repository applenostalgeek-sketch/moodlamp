# MoodLamp

Pilotage automatique de la couleur d'une lampe Philips Hue en fonction de l'état de forme physique/stress, mesuré via une montre Huawei synchronisée avec Apple Santé.

## État du projet

**Phase 0 — Validation des données** (en cours)

Avant tout développement, on vérifie que la montre Huawei pousse suffisamment de signaux (HRV, FC repos, sommeil) vers Apple Santé pour que le score de forme ait du sens.

## Setup local

```bash
cd /Users/admin/moodlamp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Phase 0 — Comment lancer l'inventaire

1. Sur iPhone : App Santé → avatar → "Exporter toutes les données santé"
2. Récupère le `.zip`, dézippe, place `export.xml` dans `./data/`
3. Lance :
   ```bash
   python tools/inventory_health.py
   ```
4. Lis `reports/inventory.md` → verdict A/B/C/D

## Architecture cible

```
Montre Huawei → Huawei Health → Apple Santé
                                     ↓
                        Health Auto Export (~5€)
                                     ↓
                            Webhook → VPS Python
                                     ↓
                       Score forme + couleur Hue
```
