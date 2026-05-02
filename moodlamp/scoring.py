"""
Scoring MoodLamp — calcul du score "forme du jour" 0-100.

Composantes (poids dans config.py) :
  - sommeil 40%   : durée + qualité (% sommeil profond) de la nuit dernière
  - rhr     30%   : FC repos du jour vs baseline 60j
  - load    20%   : cumul charge 3 derniers jours vs baseline
  - discharge 10% : minutes FC élevée depuis le réveil
  - hrv      0%   : désactivé (pas de données HRV pour l'instant)

Détection sommeil/sieste en temps réel via heuristique
(FC basse + immobilité + heure plausible).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from . import config as cfg


# ─────────────────────────────────────────────────────────────────────
# Helpers de mapping linéaire
# ─────────────────────────────────────────────────────────────────────
def _lerp(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    """Interpolation linéaire avec clamping. y(x0)=y0, y(x1)=y1."""
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    t = max(0.0, min(1.0, t))
    return y0 + t * (y1 - y0)


def _piecewise(x: float, points: list[tuple[float, float]]) -> float:
    """
    Interpolation par morceaux. points = [(x0, y0), (x1, y1), ...] triés.
    En dehors → clamp aux extrêmes.
    """
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= x <= x1:
            return _lerp(x, x0, x1, y0, y1)
    return points[-1][1]


# ─────────────────────────────────────────────────────────────────────
# Baseline : ta normale personnelle sur N jours
# ─────────────────────────────────────────────────────────────────────
@dataclass
class Baseline:
    rhr_mean: float        # FC repos moyenne
    rhr_std: float         # variabilité
    daily_steps_mean: float
    daily_kcal_mean: float
    sleep_hours_mean: float
    n_days: int            # nb de jours réellement utilisés

    def __repr__(self):
        return (f"<Baseline n={self.n_days}j  rhr={self.rhr_mean:.0f}±{self.rhr_std:.1f}  "
                f"steps={self.daily_steps_mean:,.0f}/j  "
                f"kcal={self.daily_kcal_mean:,.0f}/j  "
                f"sleep={self.sleep_hours_mean:.1f}h>")


def compute_baseline(
    data: dict[str, pd.DataFrame],
    at: datetime,
    days: int = cfg.BASELINE_DAYS,
) -> Baseline:
    """
    Calcule la baseline glissante des `days` jours précédant `at`.
    """
    cutoff_start = at - timedelta(days=days)

    # FC repos
    rhr = data["resting_hr"]
    rhr_window = rhr[(rhr["ts"] >= cutoff_start) & (rhr["ts"] < at)]
    rhr_mean = rhr_window["bpm"].mean() if not rhr_window.empty else 60.0
    rhr_std = rhr_window["bpm"].std() if len(rhr_window) > 1 else 3.0

    # Pas par jour
    steps = data["steps"]
    steps_window = steps[(steps["ts"] >= cutoff_start) & (steps["ts"] < at)].copy()
    if not steps_window.empty:
        steps_window["date"] = steps_window["ts"].dt.tz_convert(at.tzinfo).dt.date
        daily = steps_window.groupby("date")["count"].sum()
        steps_mean = daily.mean()
    else:
        steps_mean = 8000.0

    # Calories actives par jour
    kcal = data["active_energy"]
    kcal_window = kcal[(kcal["ts"] >= cutoff_start) & (kcal["ts"] < at)].copy()
    if not kcal_window.empty:
        kcal_window["date"] = kcal_window["ts"].dt.tz_convert(at.tzinfo).dt.date
        daily_k = kcal_window.groupby("date")["kcal"].sum()
        kcal_mean = daily_k.mean()
    else:
        kcal_mean = 400.0

    # Heures de sommeil par nuit (on somme les phases "Asleep*" hors Awake/InBed)
    sleep = data["sleep"]
    sleep_window = sleep[(sleep["start"] >= cutoff_start) & (sleep["start"] < at)]
    asleep_mask = sleep_window["phase"].isin(
        ["AsleepDeep", "AsleepCore", "AsleepREM", "AsleepUnspecified", "Asleep"]
    )
    asleep = sleep_window[asleep_mask].copy()
    if not asleep.empty:
        asleep["night"] = asleep["end"].dt.tz_convert(at.tzinfo).dt.date
        per_night = asleep.groupby("night")["minutes"].sum() / 60
        sleep_mean = per_night.mean()
        n_days = len(per_night)
    else:
        sleep_mean = 7.0
        n_days = 0

    return Baseline(
        rhr_mean=float(rhr_mean),
        rhr_std=float(rhr_std),
        daily_steps_mean=float(steps_mean),
        daily_kcal_mean=float(kcal_mean),
        sleep_hours_mean=float(sleep_mean),
        n_days=int(n_days),
    )


# ─────────────────────────────────────────────────────────────────────
# Composante 1 : SOMMEIL (nuit dernière)
# ─────────────────────────────────────────────────────────────────────
def _last_night(
    sleep_df: pd.DataFrame,
    at: datetime,
) -> pd.DataFrame:
    """
    Renvoie les sessions de sommeil de la "nuit dernière", càd la dernière
    session de sommeil dont la fin est avant `at`.
    """
    if sleep_df.empty:
        return sleep_df
    # On prend toutes les sessions qui se terminent avant `at`
    past = sleep_df[sleep_df["end"] < at]
    if past.empty:
        return past
    # Dernière fin = approximation du dernier réveil
    last_wake = past["end"].max()
    # Toutes les sessions dont la fin est dans les 16h précédant le réveil
    # (large pour englober une nuit complète)
    night_start = last_wake - timedelta(hours=16)
    return past[past["end"] > night_start]


def score_sleep(sleep_df: pd.DataFrame, at: datetime) -> tuple[float, dict]:
    night = _last_night(sleep_df, at)
    asleep_phases = ["AsleepDeep", "AsleepCore", "AsleepREM",
                     "AsleepUnspecified", "Asleep"]
    asleep = night[night["phase"].isin(asleep_phases)]

    if asleep.empty:
        return 50.0, {"hours": 0, "deep_pct": 0, "note": "aucune donnée"}

    total_min = asleep["minutes"].sum()
    deep_min = asleep[asleep["phase"] == "AsleepDeep"]["minutes"].sum()
    hours = total_min / 60
    deep_pct = (deep_min / total_min * 100) if total_min > 0 else 0

    # Note durée
    s = cfg.SLEEP
    duration_score = _piecewise(hours, [
        (s["duration_terrible"], 0),
        (s["duration_poor"],     25),
        (s["duration_good"],     75),
        (s["duration_excellent"], 100),
    ])
    # Note qualité (% profond)
    quality_score = _piecewise(deep_pct, [
        (0,                          0),
        (s["deep_min_pct"],         30),
        (s["deep_target_pct"],     100),
    ])

    final = (duration_score * s["duration_weight"]
             + quality_score * s["deep_weight"])

    return float(final), {
        "hours": round(hours, 2),
        "deep_pct": round(deep_pct, 1),
        "duration_score": round(duration_score, 1),
        "quality_score": round(quality_score, 1),
    }


# ─────────────────────────────────────────────────────────────────────
# Composante 2 : FC AU REPOS
# ─────────────────────────────────────────────────────────────────────
def score_rhr(rhr_df: pd.DataFrame, baseline: Baseline,
              at: datetime) -> tuple[float, dict]:
    """
    Compare la FC repos la plus récente (≤ 36h avant `at`) à la baseline.
    """
    cutoff = at - timedelta(hours=36)
    recent = rhr_df[(rhr_df["ts"] >= cutoff) & (rhr_df["ts"] <= at)]
    if recent.empty:
        return 50.0, {"current": None, "baseline": baseline.rhr_mean,
                      "delta": None, "note": "pas de FC repos récente"}

    current = float(recent["bpm"].iloc[-1])
    delta = current - baseline.rhr_mean

    # Mapping linéaire :
    #   delta = excellent_delta_bpm (-3) → note 100
    #   delta = 0                        → note 50
    #   delta = critical_delta_bpm (+8)  → note 0
    r = cfg.RHR
    score = _piecewise(delta, [
        (r["excellent_delta_bpm"], 100),
        (0,                         50),
        (r["critical_delta_bpm"],    0),
    ])

    return float(score), {
        "current": round(current, 1),
        "baseline": round(baseline.rhr_mean, 1),
        "delta": round(delta, 1),
    }


# ─────────────────────────────────────────────────────────────────────
# Composante 3 : CHARGE (3 derniers jours)
# ─────────────────────────────────────────────────────────────────────
def score_load(steps_df: pd.DataFrame, kcal_df: pd.DataFrame,
               baseline: Baseline, at: datetime) -> tuple[float, dict]:
    window = timedelta(days=cfg.LOAD["window_days"])
    cutoff = at - window
    s = steps_df[(steps_df["ts"] >= cutoff) & (steps_df["ts"] <= at)]
    k = kcal_df[(kcal_df["ts"] >= cutoff) & (kcal_df["ts"] <= at)]
    steps_total = s["count"].sum() if not s.empty else 0
    kcal_total = k["kcal"].sum() if not k.empty else 0

    expected_steps = baseline.daily_steps_mean * cfg.LOAD["window_days"]
    expected_kcal = baseline.daily_kcal_mean * cfg.LOAD["window_days"]

    # Ratio combiné (moyenne arithmétique des deux ratios)
    if expected_steps > 0 and expected_kcal > 0:
        ratio = 0.5 * (steps_total / expected_steps + kcal_total / expected_kcal)
    elif expected_steps > 0:
        ratio = steps_total / expected_steps
    else:
        ratio = 1.0

    L = cfg.LOAD
    score = _piecewise(ratio, [
        (L["ratio_low"],       90),
        (L["ratio_normal"],    70),
        (L["ratio_high"],      40),
        (L["ratio_overload"],   0),
    ])

    return float(score), {
        "steps_3d": int(steps_total),
        "kcal_3d": int(kcal_total),
        "expected_steps_3d": int(expected_steps),
        "expected_kcal_3d": int(expected_kcal),
        "ratio": round(ratio, 2),
    }


# ─────────────────────────────────────────────────────────────────────
# Composante 4 : DÉCHARGE (depuis le réveil)
# ─────────────────────────────────────────────────────────────────────
def _last_wake_time(sleep_df: pd.DataFrame, at: datetime) -> datetime | None:
    """Heure de fin de la dernière session de sommeil avant `at`."""
    night = _last_night(sleep_df, at)
    if night.empty:
        return None
    return night["end"].max()


def score_discharge(hr_df: pd.DataFrame, sleep_df: pd.DataFrame,
                    at: datetime) -> tuple[float, dict]:
    wake = _last_wake_time(sleep_df, at)
    if wake is None:
        # Fallback : on prend "depuis 6h aujourd'hui"
        wake = at.replace(hour=6, minute=0, second=0, microsecond=0)
        if wake > at:
            wake -= timedelta(days=1)

    awake_hr = hr_df[(hr_df["ts"] >= wake) & (hr_df["ts"] <= at)]
    if awake_hr.empty:
        return 70.0, {"minutes_high_hr": 0, "since_wake_h": 0,
                      "note": "pas de données FC depuis le réveil"}

    # Approximation : chaque mesure FC > seuil ≈ 1 min de FC élevée
    # (Huawei sample ~ toutes les 1-2 min, donc 1 mesure ≈ 1 min)
    threshold = cfg.DISCHARGE["high_hr_threshold"]
    high_count = int((awake_hr["bpm"] > threshold).sum())

    D = cfg.DISCHARGE
    score = _piecewise(high_count, [
        (D["minutes_low"],     90),
        (D["minutes_normal"],  60),
        (D["minutes_high"],    20),
        (D["minutes_extreme"],  0),
    ])

    return float(score), {
        "minutes_high_hr": high_count,
        "since_wake_h": round((at - wake).total_seconds() / 3600, 1),
    }


# ─────────────────────────────────────────────────────────────────────
# Détection sommeil/sieste en temps réel (heuristique)
# ─────────────────────────────────────────────────────────────────────
def detect_asleep(hr_df: pd.DataFrame, steps_df: pd.DataFrame,
                  baseline: Baseline, at: datetime) -> tuple[bool, dict]:
    SD = cfg.SLEEP_DETECTION
    window = timedelta(minutes=SD["window_minutes"])
    cutoff = at - window

    recent_hr = hr_df[(hr_df["ts"] >= cutoff) & (hr_df["ts"] <= at)]
    recent_steps = steps_df[(steps_df["ts"] >= cutoff) & (steps_df["ts"] <= at)]

    if recent_hr.empty:
        return False, {"reason": "pas de FC récente"}

    fc_mean = float(recent_hr["bpm"].mean())
    steps_total = int(recent_steps["count"].sum()) if not recent_steps.empty else 0

    # Heure locale
    local_hour = at.astimezone().hour

    is_night = (local_hour >= SD["night_start_hour"]
                or local_hour < SD["night_end_hour"])
    is_nap_window = (SD["nap_start_hour"] <= local_hour < SD["nap_end_hour"])

    fc_low = fc_mean <= baseline.rhr_mean + SD["max_fc_above_rhr"]
    immobile = steps_total <= SD["max_steps"]
    plausible = is_night or is_nap_window

    asleep = fc_low and immobile and plausible

    return asleep, {
        "fc_mean_15min": round(fc_mean, 1),
        "rhr_baseline": round(baseline.rhr_mean, 1),
        "steps_15min": steps_total,
        "local_hour": local_hour,
        "is_night": is_night,
        "is_nap_window": is_nap_window,
        "fc_low": fc_low,
        "immobile": immobile,
    }


# ─────────────────────────────────────────────────────────────────────
# Scorer global
# ─────────────────────────────────────────────────────────────────────
@dataclass
class FormScore:
    score: float
    components: dict[str, float]
    components_detail: dict[str, dict]
    is_asleep: bool
    asleep_detail: dict
    baseline: Baseline
    timestamp: datetime
    confidence: float

    def __repr__(self):
        return (f"<FormScore {self.score:.0f}/100 "
                f"asleep={self.is_asleep}  "
                f"sleep={self.components.get('sleep',0):.0f} "
                f"rhr={self.components.get('rhr',0):.0f} "
                f"load={self.components.get('load',0):.0f} "
                f"discharge={self.components.get('discharge',0):.0f}>")


class FormScorer:
    def __init__(self, data: dict[str, pd.DataFrame]):
        self.data = data

    def compute(self, at: datetime | None = None) -> FormScore:
        if at is None:
            at = datetime.now(timezone.utc)
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)

        baseline = compute_baseline(self.data, at)

        sleep_score, sleep_det = score_sleep(self.data["sleep"], at)
        rhr_score, rhr_det = score_rhr(self.data["resting_hr"], baseline, at)
        load_score, load_det = score_load(
            self.data["steps"], self.data["active_energy"], baseline, at,
        )
        discharge_score, discharge_det = score_discharge(
            self.data["heart_rate"], self.data["sleep"], at,
        )

        components = {
            "sleep":     sleep_score,
            "rhr":       rhr_score,
            "load":      load_score,
            "discharge": discharge_score,
        }
        details = {
            "sleep":     sleep_det,
            "rhr":       rhr_det,
            "load":      load_det,
            "discharge": discharge_det,
        }

        # Score pondéré
        total_w = sum(cfg.WEIGHTS[k] for k in components)
        if total_w == 0:
            score = 50.0
        else:
            score = sum(
                components[k] * cfg.WEIGHTS[k] for k in components
            ) / total_w

        # Détection sommeil
        is_asleep, asleep_det = detect_asleep(
            self.data["heart_rate"], self.data["steps"], baseline, at,
        )

        # Confiance : basée sur la fraîcheur des données
        # (si la dernière FC date de >2h, on baisse la confiance)
        last_hr = self.data["heart_rate"]["ts"].max() if not self.data["heart_rate"].empty else None
        if last_hr is not None:
            age_h = (at - last_hr).total_seconds() / 3600
            if age_h <= 0.5:
                confidence = 1.0
            elif age_h <= 2:
                confidence = 0.85
            elif age_h <= 12:
                confidence = 0.6
            else:
                confidence = 0.3
        else:
            confidence = 0.0

        return FormScore(
            score=round(score, 1),
            components={k: round(v, 1) for k, v in components.items()},
            components_detail=details,
            is_asleep=is_asleep,
            asleep_detail=asleep_det,
            baseline=baseline,
            timestamp=at,
            confidence=confidence,
        )
