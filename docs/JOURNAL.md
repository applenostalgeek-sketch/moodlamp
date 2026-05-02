# Journal MoodLamp

Trace des décisions et de l'état d'avancement, à mettre à jour à chaque session.

---

## Session 2 — 2026-05-02 (serveur web local)

### Ajouts
- `moodlamp/server.py` : mini serveur HTTP (stdlib, port 8765)
  - `GET /` → page HTML avec score actuel
  - `POST /refresh` → re-parse l'XML, recharge le cache
  - `GET /api/score` → JSON brut
- `tools/score_to_html.py` : génère un HTML statique (pour usage hors serveur)
- `start.sh` : lance le serveur + ouvre le navigateur
- `update.sh` : génère HTML statique (alternative sans serveur)

### Améliorations UX HTML
- Bouton "🔄 Mettre à jour les données" qui appelle /refresh sans terminal
- Indicateur de fraîcheur (dernière FC il y a X min)
- Warning si données > 1h
- Toast de feedback pendant le refresh
- Auto-refresh page 60s

### Score testé sur données du 2 mai 10h
- Score 42 ORANGE
- Tiré vers le bas par sommeil 4.4h dont 5% profond (validé par Jo : ça correspond à son ressenti)
- Charge 3j basse (ratio 0.79) et décharge faible → ne compensent pas

### Décision Jo
- Validé que la formule colle au ressenti → on passe à l'auto-refresh
- Solution A (Raccourcis iOS gratuit) à essayer en priorité avant de payer Premium
- D'abord vouloir un bouton "MAJ" simple dans le HTML : ✅ livré

### Limitation persistante
Le bouton "MAJ" ne récupère PAS les données depuis Apple Santé tout seul.
Il faut toujours :
1. Refaire un export Apple Santé sur l'iPhone (manuel)
2. Remplacer le fichier dans data/
3. Cliquer "MAJ" → recharge le cache

Pour le vrai auto, prochaine étape = Solution A (Raccourcis iOS) ou B (Health Auto Export Premium).

---

## Session 1 — 2026-04-29 (Phase 0 + début Phase 1)

### Objectif validé du projet

Une lampe Philips Hue qui change de couleur selon l'état de forme physique
mesuré via la montre Huawei → Apple Santé.

**Étape 1 (priorité)** : afficher le score + couleur sur l'ordinateur
(pas de lampe Hue tout de suite). On ne branchera la lampe qu'une fois la
formule de score validée.

### Palette de couleurs validée

| Couleur | Quand | Logique |
|---|---|---|
| 🔵 Bleu | Sommeil/sieste détectés en temps réel | Heuristique FC basse + immobilité + heure plausible |
| 🔴 Rouge | Score 0-30 | Très fatigué |
| 🟠 Orange | Score 30-50 | Fatigue marquée |
| 🟡 Jaune | Score 50-70 | Correct |
| 🟢 Vert | Score 70-100 | En forme |

### Phase 0 — VALIDÉE ✅

**Inventaire des données Apple Santé :**
- 800 Mo XML, 2.2M records, 7 ans d'historique
- Verdict : **B** (FC, FC repos, sommeil détaillé, SpO2 — mais **HRV absent**)
- HRV = "Variabilité de la fréquence cardiaque" = LE meilleur marqueur
  unique de récupération du système nerveux. Huawei ne le pousse pas
  vers Apple Santé.
- Solution : installer **HRV4Training** (~10€) en parallèle. Mesure 30s
  au réveil. Le HRV sera intégré comme 5e composante quand 7+ jours
  seront accumulés.
- Voir `docs/IOS_SETUP_HRV.md`

**Problème détecté** : double-comptage des pas (18k/jour artificiel à
cause de 3 sources Huawei qui se cumulent). Résolu en Phase 1 par la
détection automatique de la "meilleure source".

### Phase 1 — EN COURS (briques 1-3 livrées)

**Architecture choisie** : MVP local sur le Mac de Jo, pas encore de VPS.

**Briques livrées** :
1. ✅ `moodlamp/health_loader.py` — parse XML, détecte la meilleure
   source par signal, sauvegarde un cache CSV (~28 Mo)
2. ✅ `moodlamp/config.py` — tous les paramètres ajustables
   (poids, seuils sommeil/RHR/charge/décharge, plages couleurs)
3. ✅ `moodlamp/scoring.py` — `FormScorer` avec compute_baseline +
   compute (4 composantes + détection sommeil temps réel)
4. ✅ `tools/score_now.py` — affichage terminal coloré

**Pondération initiale validée** :
- Sommeil 40% (durée + % profond)
- FC repos vs baseline 30%
- Charge 3 derniers jours 20%
- Décharge depuis le réveil 10%
- HRV 0% (activable plus tard)

**Baseline glissante 60 jours** (option C, compromis stabilité/réactivité).

**Premier test réel** (29/04 10h22) :
- Score : 68/100 → JAUNE
- Sommeil 100/100 (8.2h, 19% profond)
- FC repos 40/100 (47 vs baseline 45 = +2)
- Charge 37/100 (46k pas en 3j = +32% vs normale)
- Décharge 90/100 (0 min FC>100 ce matin)

### Limitation à savoir : pas de vrai temps réel

Le calcul lit un export Apple Santé statique (`data/export.xml`).
Données figées au moment de l'export. Pour avoir du vrai temps réel,
il faudra installer Health Auto Export (Phase 4 du brief original).

**Plan actuel** : valider la formule sur des journées passées avec le
ressenti de Jo, puis basculer en temps réel quand la formule est
calibrée.

### Prochaines étapes

**Côté Jo (en parallèle, non urgent)** :
- Vérifier toggle Huawei pour HRV (5 min, peu d'espoir)
- Si rien : installer HRV4Training

**Côté code (à faire)** :
1. Tester le scoring sur 5-7 journées passées avec le ressenti de Jo
   (validation de la formule)
2. Ajuster les poids/seuils si nécessaire
3. Une fois la formule OK, créer un dashboard web simple (HTML local
   qui se rafraîchit auto)
4. Plus tard : Health Auto Export → vrai temps réel
5. Plus tard : intégration Hue (Phase 3 du brief)

### Choix techniques notables

- **Python config.py** au lieu de YAML (zéro deps, lisible)
- **Cache CSV** pour éviter de re-parser 800 Mo à chaque calcul
- **Détection auto de la meilleure source** par signal (résout le
  double-comptage)
- **Stack actuelle** : Python 3.13 + pandas + matplotlib + numpy
  (toutes deps déjà présentes système)

### Structure du repo

```
/Users/admin/moodlamp/
├── moodlamp/
│   ├── __init__.py
│   ├── config.py           # tous les paramètres
│   ├── health_loader.py    # parse XML + cache CSV
│   └── scoring.py          # FormScorer
├── tools/
│   ├── inventory_health.py # rapport markdown + verdict
│   ├── explore_health.py   # graphes 30j
│   └── score_now.py        # CLI affichage score
├── data/
│   ├── apple_health_export/    # export brut iPhone
│   ├── export.xml → symlink
│   └── cache/              # CSV par signal (gitignored)
├── reports/
│   ├── inventory.md
│   └── charts/             # heatmap_fc, fc_repos, sommeil, pas
├── docs/
│   ├── IOS_SETUP_HRV.md
│   └── JOURNAL.md          # ce fichier
├── tests/                  # vide pour l'instant
├── .gitignore
├── README.md
└── requirements.txt
```

### Commandes utiles pour reprendre

```bash
cd /Users/admin/moodlamp

# Score maintenant
PYTHONPATH=. python3 tools/score_now.py

# Score à une date précise
PYTHONPATH=. python3 tools/score_now.py --at "2026-04-25 09:00"

# Forcer le re-parse de l'XML (après nouvel export Apple Santé)
PYTHONPATH=. python3 tools/score_now.py --refresh

# Re-générer les graphes 30j
python3 tools/explore_health.py

# Re-générer l'inventaire complet
python3 tools/inventory_health.py
```
