#!/usr/bin/env python3
"""
Visualisation exploratoire des données Apple Santé sur les 30 derniers jours.

Génère 4 graphiques dans reports/charts/ :
  - heatmap_fc.png       : FC moyenne par heure x jour
  - sommeil.png          : durée de sommeil par nuit (avec phases si dispo)
  - pas.png              : pas par jour
  - fc_repos.png         : FC au repos jour par jour

Filtre les sources pour ne garder que les données récentes pertinentes
(Huawei Santé surtout — exclut les vieilles sources Apple Watch / autres
iPhones).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
EXPORT_PATH = ROOT / "data" / "export.xml"
CHARTS_DIR = ROOT / "reports" / "charts"

WINDOW_DAYS = 30

# Sources à conserver — toutes celles contenant "HUAWEI" + "jo" (iPhone perso)
def is_relevant_source(src: str) -> bool:
    s = src.lower()
    if "huawei" in s:
        return True
    if s == "jo":
        return True
    if s == "santé" or s == "iphone":
        # garde l'iphone "principal" (pas "iPhone de MARINE")
        return True
    return False


def parse_apple_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def stream_records(xml_path: Path, types_wanted: set[str], cutoff: datetime):
    """Yield records dans la fenêtre, des types voulus, sources pertinentes."""
    context = ET.iterparse(str(xml_path), events=("end",))
    for _, elem in context:
        if elem.tag != "Record":
            elem.clear()
            continue
        t = elem.get("type", "")
        if t not in types_wanted:
            elem.clear()
            continue
        src = elem.get("sourceName", "")
        if not is_relevant_source(src):
            elem.clear()
            continue
        sd = parse_apple_date(elem.get("startDate", ""))
        if sd is None or sd < cutoff:
            elem.clear()
            continue
        ed = parse_apple_date(elem.get("endDate", ""))
        val = elem.get("value", "")
        yield t, src, sd, ed, val
        elem.clear()


def collect_data(xml_path: Path) -> dict:
    """Un seul parcours du XML, on charge tout ce qu'il faut en RAM."""
    types_wanted = {
        "HKQuantityTypeIdentifierHeartRate",
        "HKQuantityTypeIdentifierRestingHeartRate",
        "HKQuantityTypeIdentifierStepCount",
        "HKCategoryTypeIdentifierSleepAnalysis",
    }
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)

    fc_by_hour_day = defaultdict(list)   # (date, hour) -> [bpm, ...]
    rhr_by_day = defaultdict(list)       # date -> [bpm, ...]
    steps_by_day = defaultdict(float)    # date -> sum
    sleep_by_night = defaultdict(lambda: defaultdict(float))  # night_date -> {phase: minutes}

    n = 0
    for t, src, sd, ed, val in stream_records(xml_path, types_wanted, cutoff):
        local = sd.astimezone()  # heure locale
        d = local.date()

        if t == "HKQuantityTypeIdentifierHeartRate":
            try:
                fc_by_hour_day[(d, local.hour)].append(float(val))
            except ValueError:
                pass
        elif t == "HKQuantityTypeIdentifierRestingHeartRate":
            try:
                rhr_by_day[d].append(float(val))
            except ValueError:
                pass
        elif t == "HKQuantityTypeIdentifierStepCount":
            try:
                steps_by_day[d] += float(val)
            except ValueError:
                pass
        elif t == "HKCategoryTypeIdentifierSleepAnalysis":
            if ed is None:
                continue
            duration_min = (ed - sd).total_seconds() / 60
            # Convention : une nuit "appartient" au jour du réveil
            night_date = ed.astimezone().date()
            # value = "HKCategoryValueSleepAnalysisAsleepREM" / Core / Deep / InBed / Awake
            phase = val.replace("HKCategoryValueSleepAnalysis", "")
            sleep_by_night[night_date][phase] += duration_min

        n += 1
        if n % 100_000 == 0:
            print(f"  ... {n:,} records pertinents", file=sys.stderr)

    return {
        "fc_by_hour_day": fc_by_hour_day,
        "rhr_by_day": rhr_by_day,
        "steps_by_day": steps_by_day,
        "sleep_by_night": sleep_by_night,
    }


def plot_heatmap_fc(data: dict, out: Path):
    """Heatmap FC moyenne, lignes = jours, colonnes = heures."""
    fc = data["fc_by_hour_day"]
    if not fc:
        print("  ⚠️ Pas de données FC", file=sys.stderr)
        return

    days = sorted({d for (d, h) in fc.keys()})
    matrix = np.full((len(days), 24), np.nan)
    for i, d in enumerate(days):
        for h in range(24):
            vals = fc.get((d, h), [])
            if vals:
                matrix[i, h] = sum(vals) / len(vals)

    fig, ax = plt.subplots(figsize=(12, max(4, len(days) * 0.25)))
    im = ax.imshow(matrix, aspect="auto", cmap="RdYlGn_r",
                   vmin=50, vmax=120, interpolation="nearest")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h}h" for h in range(0, 24, 2)])
    ax.set_yticks(range(len(days)))
    ax.set_yticklabels([d.strftime("%d/%m") for d in days], fontsize=8)
    ax.set_xlabel("Heure de la journée")
    ax.set_title(f"FC moyenne par heure — {WINDOW_DAYS} derniers jours")
    plt.colorbar(im, ax=ax, label="bpm")
    plt.tight_layout()
    plt.savefig(out, dpi=110)
    plt.close()
    print(f"  ✅ {out.name}")


def plot_rhr(data: dict, out: Path):
    rhr = data["rhr_by_day"]
    if not rhr:
        print("  ⚠️ Pas de FC repos", file=sys.stderr)
        return
    days = sorted(rhr.keys())
    vals = [sum(rhr[d]) / len(rhr[d]) for d in days]

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(days, vals, marker="o", color="#c0392b", linewidth=2)
    if len(vals) >= 7:
        ma = np.convolve(vals, np.ones(7) / 7, mode="valid")
        ma_days = days[6:]
        ax.plot(ma_days, ma, color="#2c3e50", linewidth=1.5,
                linestyle="--", label="Moyenne mobile 7j")
        ax.legend()
    ax.set_ylabel("FC repos (bpm)")
    ax.set_title(f"FC au repos — {WINDOW_DAYS} derniers jours")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(out, dpi=110)
    plt.close()
    print(f"  ✅ {out.name}")


def plot_steps(data: dict, out: Path):
    steps = data["steps_by_day"]
    if not steps:
        print("  ⚠️ Pas de données pas", file=sys.stderr)
        return
    days = sorted(steps.keys())
    vals = [steps[d] for d in days]
    avg = sum(vals) / len(vals)

    fig, ax = plt.subplots(figsize=(11, 4))
    colors = ["#27ae60" if v >= avg else "#95a5a6" for v in vals]
    ax.bar(days, vals, color=colors, width=0.8)
    ax.axhline(avg, color="#2c3e50", linestyle="--",
               label=f"Moyenne : {avg:,.0f} pas")
    ax.set_ylabel("Pas")
    ax.set_title(f"Pas par jour — {WINDOW_DAYS} derniers jours")
    ax.grid(alpha=0.3, axis="y")
    ax.legend()
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(out, dpi=110)
    plt.close()
    print(f"  ✅ {out.name}")


def plot_sleep(data: dict, out: Path):
    sleep = data["sleep_by_night"]
    if not sleep:
        print("  ⚠️ Pas de données sommeil", file=sys.stderr)
        return

    nights = sorted(sleep.keys())
    # Phases qu'on veut empiler (du plus profond au plus léger)
    phase_order = [
        ("AsleepDeep", "#1a3a52", "Profond"),
        ("AsleepCore", "#3498db", "Léger/Core"),
        ("AsleepREM", "#9b59b6", "REM"),
        ("Asleep", "#7f8c8d", "Asleep (non détaillé)"),
        ("AsleepUnspecified", "#7f8c8d", "Asleep (unspec.)"),
        ("Awake", "#e74c3c", "Éveillé"),
        ("InBed", "#bdc3c7", "Au lit (non détecté)"),
    ]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    bottoms = np.zeros(len(nights))
    for phase_key, color, label in phase_order:
        values = np.array([sleep[n].get(phase_key, 0) / 60 for n in nights])
        if values.sum() == 0:
            continue
        ax.bar(nights, values, bottom=bottoms, color=color,
               label=label, width=0.8)
        bottoms += values

    ax.set_ylabel("Heures")
    ax.set_title(f"Sommeil par nuit — {WINDOW_DAYS} derniers jours")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(out, dpi=110)
    plt.close()
    print(f"  ✅ {out.name}")


def main():
    if not EXPORT_PATH.exists():
        print(f"❌ Fichier introuvable : {EXPORT_PATH}", file=sys.stderr)
        sys.exit(1)

    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"📂 Lecture {EXPORT_PATH.name} (fenêtre {WINDOW_DAYS}j)...",
          file=sys.stderr)
    data = collect_data(EXPORT_PATH)

    print("🎨 Génération des graphes...", file=sys.stderr)
    plot_heatmap_fc(data, CHARTS_DIR / "heatmap_fc.png")
    plot_rhr(data, CHARTS_DIR / "fc_repos.png")
    plot_steps(data, CHARTS_DIR / "pas.png")
    plot_sleep(data, CHARTS_DIR / "sommeil.png")

    print(f"\n✅ Graphes dans : {CHARTS_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
