#!/usr/bin/env python3
"""
Affiche le score forme du jour et la couleur correspondante.

Usage :
  python tools/score_now.py                    # maintenant
  python tools/score_now.py --at "2026-04-25 09:00"  # à un instant passé
  python tools/score_now.py --at "2026-04-25"        # à 12h ce jour-là
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from moodlamp import config as cfg
from moodlamp.health_loader import load_or_refresh
from moodlamp.scoring import FormScorer


# Codes ANSI pour couleur dans le terminal
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"

# RGB → ANSI 256
def ansi_bg(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\033[48;2;{r};{g};{b}m"


def color_for_score(score: float, is_asleep: bool) -> tuple[str, str]:
    if is_asleep:
        return cfg.COLOR_SLEEP
    for lo, hi, name, hx in cfg.COLOR_BANDS:
        if lo <= score < hi:
            return name, hx
    last = cfg.COLOR_BANDS[-1]
    return last[2], last[3]


def parse_at(s: str | None) -> datetime | None:
    if s is None:
        return None
    fmts = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
    for f in fmts:
        try:
            d = datetime.strptime(s, f)
            if f == "%Y-%m-%d":
                d = d.replace(hour=12)
            return d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Format date invalide : {s}")


def bar(value: float, width: int = 30) -> str:
    filled = int(value / 100 * width)
    return "█" * filled + "░" * (width - filled)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--at", type=str, default=None,
                   help="Instant cible (défaut : maintenant)")
    p.add_argument("--refresh", action="store_true",
                   help="Re-parse l'XML avant calcul")
    args = p.parse_args()

    at = parse_at(args.at)
    data = load_or_refresh(force_refresh=args.refresh)
    scorer = FormScorer(data)
    result = scorer.compute(at=at)

    color_name, color_hex = color_for_score(result.score, result.is_asleep)
    bg = ansi_bg(color_hex)

    # En-tête
    ts_local = result.timestamp.astimezone()
    print()
    print(f"{ANSI_BOLD}MoodLamp — score à {ts_local.strftime('%Y-%m-%d %H:%M')}{ANSI_RESET}")
    print()

    # Bandeau couleur
    label = f"  {color_name.upper()}  —  score {result.score:.0f}/100  "
    if result.is_asleep:
        label += "💤 (sommeil détecté)  "
    print(f"{bg}{ANSI_BOLD}{label.center(60)}{ANSI_RESET}")
    print(f"  hex {color_hex}     confiance : {result.confidence*100:.0f}%")
    print()

    # Composantes
    print(f"{ANSI_BOLD}Composantes{ANSI_RESET}")
    weights = cfg.WEIGHTS
    for key in ("sleep", "rhr", "load", "discharge"):
        v = result.components[key]
        w = weights[key]
        contrib = v * w / 100
        label = {
            "sleep": "Sommeil nuit dernière",
            "rhr": "FC repos vs baseline",
            "load": "Charge 3 derniers jours",
            "discharge": "Décharge depuis réveil",
        }[key]
        print(f"  {label:30s}  {bar(v)}  {v:5.1f}/100  "
              f"× {w}%  =  {contrib:5.1f}")
    print()

    # Détails
    print(f"{ANSI_BOLD}Détails{ANSI_RESET}")
    s = result.components_detail["sleep"]
    print(f"  Sommeil   : {s.get('hours', 0):.1f}h, "
          f"profond {s.get('deep_pct', 0):.0f}%")
    r = result.components_detail["rhr"]
    if r.get("current") is not None:
        print(f"  FC repos  : {r['current']:.0f} bpm  "
              f"(baseline {r['baseline']:.0f}, écart {r['delta']:+.1f})")
    else:
        print(f"  FC repos  : pas de donnée récente")
    L = result.components_detail["load"]
    print(f"  Charge 3j : {L['steps_3d']:,} pas, {L['kcal_3d']:,} kcal  "
          f"(ratio vs normale : {L['ratio']:.2f})")
    D = result.components_detail["discharge"]
    print(f"  Décharge  : {D['minutes_high_hr']} min FC>100 "
          f"sur {D['since_wake_h']}h éveillé")
    print()

    # Baseline
    print(f"{ANSI_BOLD}Baseline (60 derniers jours){ANSI_RESET}")
    b = result.baseline
    print(f"  FC repos {b.rhr_mean:.0f}±{b.rhr_std:.1f} bpm   "
          f"|   {b.daily_steps_mean:,.0f} pas/j   "
          f"|   {b.daily_kcal_mean:,.0f} kcal/j   "
          f"|   {b.sleep_hours_mean:.1f}h sommeil/nuit "
          f"({b.n_days} nuits)")

    # Diagnostic sommeil détecté
    if result.is_asleep:
        d = result.asleep_detail
        print()
        print(f"{ANSI_BOLD}🛌 Détection sommeil active{ANSI_RESET}")
        print(f"  FC moyenne 15 min : {d['fc_mean_15min']:.0f} bpm "
              f"(baseline RHR {d['rhr_baseline']:.0f})")
        print(f"  Pas 15 min : {d['steps_15min']}")
        print(f"  Heure locale : {d['local_hour']}h "
              f"(nuit={d['is_night']}, sieste possible={d['is_nap_window']})")
    print()


if __name__ == "__main__":
    main()
