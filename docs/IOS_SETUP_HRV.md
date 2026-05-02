# Récupérer le HRV (à faire en parallèle du dev)

Verdict Phase 0 : ta montre Huawei pousse FC, FC repos, sommeil détaillé,
SpO2 — mais **pas de HRV**. On peut faire MoodLamp sans, mais avec un
HRV au réveil le score sera nettement plus fin (le HRV au réveil est le
meilleur marqueur unique de l'état du système nerveux autonome).

## Étape 1 — Vérifier le toggle Huawei (5 min, gratuit)

1. Ouvrir **Huawei Santé** sur l'iPhone
2. Aller dans **Moi → Paramètres → Données** (ou "Source de données" / "Compte")
3. Chercher une option **"Apple Santé"** ou **"HealthKit"**
4. Vérifier que **toutes les catégories sont activées**, en particulier
   "Variabilité de la fréquence cardiaque" / "HRV"
5. Si l'option n'existe pas → passer à l'étape 2

> Selon le modèle de la montre (GT, Watch, Band) et la version de
> Huawei Santé, le HRV est ou n'est pas exposé via HealthKit. Dans la
> majorité des cas, il ne l'est pas.

## Étape 2 — HRV4Training (~10€, recommandé)

App de référence chez les sportifs. Mesure HRV via la caméra du
téléphone en 30s au réveil. Plus fiable qu'un HRV de montre.

1. App Store → **HRV4Training**
2. Configurer : autoriser l'écriture dans Apple Santé
3. Routine : chaque matin, dans le lit, 30s doigt sur la caméra
4. Les données arrivent dans Apple Santé sous le type
   `HeartRateVariabilitySDNN`, source = HRV4Training

Une fois 7 jours de données accumulés, on peut activer la composante
HRV dans `moodlamp/scoring.py` (un paramètre dans `config.yaml`).

## Étape 3 — Alternative gratuite (moins fiable)

**Welltory** ou **Elite HRV** ont des versions gratuites. Qualité
variable selon ton iPhone et la luminosité ambiante. À tester si tu
ne veux pas payer HRV4Training.

## Comment savoir si ça marche

Relancer l'inventaire après 3-4 jours :

```bash
python tools/inventory_health.py
```

Le verdict devrait passer de **B** à **A** si HRV4Training pousse
correctement.
