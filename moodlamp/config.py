"""
Configuration MoodLamp — paramètres modifiables sans toucher au code.

Tout ce qui est ajustable est ici : poids des composantes, seuils de
détection sommeil, plages de couleurs, etc.

Pour ajuster : édite ce fichier et relance le calcul. Pas besoin de
redémarrer quoi que ce soit.
"""

# ─────────────────────────────────────────────────────────────────────
# BASELINE — fenêtre de référence pour calculer "ta normale"
# ─────────────────────────────────────────────────────────────────────
BASELINE_DAYS = 60  # validé par Jo (option C, compromis stabilité/réactivité)


# ─────────────────────────────────────────────────────────────────────
# POIDS DES COMPOSANTES — total = 100%
# ─────────────────────────────────────────────────────────────────────
# Si tu ajoutes/changes : la somme doit faire 100.
# Le HRV n'est pas activé pour l'instant (poids 0). Quand HRV4Training
# sera installé et qu'on aura 7+ jours de données, on lui donnera un
# poids et on rééquilibrera les autres.
WEIGHTS = {
    "sleep":      40,  # nuit dernière (durée + qualité phases)
    "rhr":        30,  # FC repos vs baseline
    "load":       20,  # charge accumulée 3 derniers jours
    "discharge":  10,  # décharge depuis le réveil aujourd'hui
    "hrv":         0,  # désactivé tant que pas de HRV4Training
}


# ─────────────────────────────────────────────────────────────────────
# SOMMEIL — seuils pour la note 0-100 de la composante "sommeil"
# ─────────────────────────────────────────────────────────────────────
SLEEP = {
    # Durée totale de sommeil en heures
    "duration_excellent": 8.0,   # 8h+ → durée notée 100
    "duration_good":      7.0,   # 7h → durée notée ~75
    "duration_poor":      5.0,   # 5h → durée notée ~25
    "duration_terrible":  3.5,   # ≤3h30 → durée notée 0

    # Part de sommeil profond (en % du total)
    # Calibré sur la distribution réelle du capteur Huawei (61 nuits) :
    # médiane 28%, p10 18%, p75 35%. Norme médicale Apple = 13-23%, Huawei
    # sur-rapporte d'~1.5x — d'où ces seuils plus hauts qu'en standard.
    "deep_target_pct":   35.0,   # p75 utilisateur → note qualité 100
    "deep_min_pct":      18.0,   # p10 utilisateur → note qualité 30

    # Pondération interne entre durée et qualité
    "duration_weight":   0.65,   # 65% durée, 35% qualité (profond)
    "deep_weight":       0.35,
}


# ─────────────────────────────────────────────────────────────────────
# FC AU REPOS — comment traduire "écart vs baseline" en note 0-100
# ─────────────────────────────────────────────────────────────────────
RHR = {
    # Note 100 quand FC repos est ≤ baseline - excellent_delta (super récup)
    "excellent_delta_bpm": -3.0,

    # Note 50 quand FC repos = baseline (état normal)
    # Note 0 quand FC repos est ≥ baseline + critical_delta (alerte fatigue)
    "critical_delta_bpm":  +8.0,
}


# ─────────────────────────────────────────────────────────────────────
# CHARGE — sur les 3 derniers jours
# ─────────────────────────────────────────────────────────────────────
LOAD = {
    "window_days":           3,    # fenêtre glissante
    "ratio_low":             0.7,  # charge < 70% de la normale → bonne récup → note 90
    "ratio_normal":          1.0,  # charge = normale → note 70
    "ratio_high":            1.3,  # charge = +30% → note 40
    "ratio_overload":        1.6,  # charge = +60% → note 0
}


# ─────────────────────────────────────────────────────────────────────
# DÉCHARGE JOURNÉE — minutes passées avec FC élevée depuis le réveil
# ─────────────────────────────────────────────────────────────────────
DISCHARGE = {
    "high_hr_threshold":   100,   # bpm au-dessus duquel on compte "FC élevée"
    "minutes_low":          15,   # ≤15 min de FC élevée → note 90
    "minutes_normal":       45,   # 45 min → note 60
    "minutes_high":        120,   # 2h → note 20
    "minutes_extreme":     240,   # 4h+ → note 0
}


# ─────────────────────────────────────────────────────────────────────
# DÉTECTION SOMMEIL/SIESTE EN TEMPS RÉEL (heuristique)
# ─────────────────────────────────────────────────────────────────────
SLEEP_DETECTION = {
    "window_minutes":      15,    # on regarde les 15 dernières minutes
    "max_fc_above_rhr":     5,    # FC moyenne ≤ baseline RHR + 5 bpm
    "max_steps":            5,    # ≤ 5 pas dans la fenêtre
    "night_start_hour":    21,    # plage "nuit" : 21h → 9h
    "night_end_hour":       9,
    "nap_start_hour":      12,    # plage "sieste possible" : 12h → 17h
    "nap_end_hour":        17,
}


# ─────────────────────────────────────────────────────────────────────
# COULEURS — mapping score → couleur (palette validée 5 couleurs)
# ─────────────────────────────────────────────────────────────────────
# Format : (score_min, score_max, nom, hex)
COLOR_BANDS = [
    (  0,  30, "rouge",   "#c0392b"),
    ( 30,  50, "orange",  "#e67e22"),
    ( 50,  70, "jaune",   "#f1c40f"),
    ( 70, 100, "vert",    "#27ae60"),
]
# Bleu hors-bande, déclenché par détection sommeil
COLOR_SLEEP = ("bleu", "#2980b9")
