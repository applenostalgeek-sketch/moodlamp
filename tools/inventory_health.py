#!/usr/bin/env python3
"""
Inventaire de l'export Apple Santé.

Parse data/export.xml en streaming (iterparse) et génère :
  - reports/inventory.md : tableaux + verdict A/B/C/D
  - sortie console : même rapport pour discussion immédiate

Verdict basé sur la disponibilité des signaux critiques pour MoodLamp :
HeartRateVariabilitySDNN (HRV), RestingHeartRate, SleepAnalysis.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
EXPORT_PATH = ROOT / "data" / "export.xml"
REPORT_PATH = ROOT / "reports" / "inventory.md"

# Types critiques pour le scoring MoodLamp
CRITICAL_TYPES = {
    "HKQuantityTypeIdentifierHeartRate": "FC instantanée",
    "HKQuantityTypeIdentifierRestingHeartRate": "FC au repos",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "HRV (SDNN)",
    "HKCategoryTypeIdentifierSleepAnalysis": "Sommeil",
    "HKQuantityTypeIdentifierStepCount": "Pas",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "Calories actives",
    "HKQuantityTypeIdentifierOxygenSaturation": "SpO2",
    "HKQuantityTypeIdentifierRespiratoryRate": "Fréquence respiratoire",
}


def parse_apple_date(s: str) -> datetime | None:
    """Apple format : '2026-04-28 07:14:32 +0200'"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def short_type(t: str) -> str:
    """Raccourcit HKQuantityTypeIdentifierHeartRate → HeartRate"""
    for prefix in ("HKQuantityTypeIdentifier", "HKCategoryTypeIdentifier"):
        if t.startswith(prefix):
            return t[len(prefix):]
    return t


def stream_records(xml_path: Path):
    """Yield (type, source, start_date) en streaming pour économiser la RAM."""
    context = ET.iterparse(str(xml_path), events=("end",))
    for event, elem in context:
        if elem.tag == "Record":
            t = elem.get("type", "")
            src = elem.get("sourceName", "Unknown")
            sd = parse_apple_date(elem.get("startDate", ""))
            yield t, src, sd
            elem.clear()


def build_inventory(xml_path: Path) -> dict:
    """Parcours unique du XML, agrège tout ce dont on a besoin."""
    counts_by_type: dict[str, int] = defaultdict(int)
    sources_by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    first_by_type: dict[str, datetime] = {}
    last_by_type: dict[str, datetime] = {}
    last_30d_by_type: dict[str, int] = defaultdict(int)

    now = datetime.now(timezone.utc)
    cutoff_30d = now - timedelta(days=30)

    total = 0
    for t, src, sd in stream_records(xml_path):
        if not t:
            continue
        counts_by_type[t] += 1
        sources_by_type[t][src] += 1
        if sd is not None:
            if t not in first_by_type or sd < first_by_type[t]:
                first_by_type[t] = sd
            if t not in last_by_type or sd > last_by_type[t]:
                last_by_type[t] = sd
            if sd >= cutoff_30d:
                last_30d_by_type[t] += 1
        total += 1
        if total % 200_000 == 0:
            print(f"  ... {total:>10,} records parsés", file=sys.stderr)

    return {
        "counts": counts_by_type,
        "sources": sources_by_type,
        "first": first_by_type,
        "last": last_by_type,
        "last_30d": last_30d_by_type,
        "total": total,
    }


def fmt_date(d: datetime | None) -> str:
    return d.strftime("%Y-%m-%d") if d else "—"


def fmt_sources(srcs: dict[str, int]) -> str:
    items = sorted(srcs.items(), key=lambda x: -x[1])
    return ", ".join(f"{name} ({n:,})" for name, n in items[:4])


def freq_per_day(count_30d: int) -> str:
    if count_30d == 0:
        return "0"
    return f"{count_30d / 30:.1f}"


def compute_verdict(inv: dict) -> tuple[str, list[str]]:
    """Verdict A/B/C/D + justifications."""
    last_30d = inv["last_30d"]
    last_dates = inv["last"]

    hrv = last_30d.get("HKQuantityTypeIdentifierHeartRateVariabilitySDNN", 0)
    rhr = last_30d.get("HKQuantityTypeIdentifierRestingHeartRate", 0)
    sleep = last_30d.get("HKCategoryTypeIdentifierSleepAnalysis", 0)
    steps = last_30d.get("HKQuantityTypeIdentifierStepCount", 0)

    notes = []
    notes.append(f"HRV (30j) : {hrv} entrées — {freq_per_day(hrv)}/jour")
    notes.append(f"FC repos (30j) : {rhr} entrées — {freq_per_day(rhr)}/jour")
    notes.append(f"Sommeil (30j) : {sleep} entrées")
    notes.append(f"Pas (30j) : {steps} entrées")

    # Fraîcheur de la donnée (si dernier point > 7 jours, problème)
    now = datetime.now(timezone.utc)
    for t in ("HKQuantityTypeIdentifierHeartRate",
              "HKCategoryTypeIdentifierSleepAnalysis"):
        if t in last_dates:
            age = (now - last_dates[t]).days
            if age > 7:
                notes.append(
                    f"⚠️ {short_type(t)} : dernière donnée il y a {age} jours"
                )

    # Logique de verdict
    has_hrv_daily = hrv >= 20  # ~quotidien sur 30j
    has_rhr_daily = rhr >= 20
    has_sleep = sleep >= 20

    if has_hrv_daily and has_rhr_daily and has_sleep:
        verdict = "A"
        justif = (
            "HRV quotidien + FC repos quotidienne + sommeil détaillé. "
            "Tous les composants du score sont alimentés. Projet 100% faisable."
        )
    elif has_rhr_daily and has_sleep:
        verdict = "B"
        justif = (
            "FC repos + sommeil disponibles, mais HRV manquant ou rare. "
            "Projet faisable avec un score moins fin (le HRV est le meilleur "
            "marqueur de récupération du SNA). À envisager : pondérer "
            "davantage la FC repos et le sommeil."
        )
    elif has_sleep or has_rhr_daily:
        verdict = "C"
        justif = (
            "Données partielles. Le score sera limité aux signaux disponibles "
            "(probablement pas + sommeil ou FC seule). Alternatives à "
            "envisager : enrichir manuellement, ou réduire le scope au "
            "tracking d'activité uniquement."
        )
    else:
        verdict = "D"
        justif = (
            "Données critiques manquantes. La montre Huawei ne pousse pas "
            "(ou très peu) vers Apple Santé. Repenser le hardware : montre "
            "compatible HealthKit native (Apple Watch, Garmin, Whoop) ou "
            "récupérer les données via un autre chemin (export Huawei Health "
            "direct, API tierce)."
        )

    return verdict, notes + ["", justif]


def render_markdown(inv: dict, verdict: str, notes: list[str]) -> str:
    lines = []
    lines.append("# Inventaire Apple Santé — MoodLamp Phase 0")
    lines.append("")
    lines.append(f"**Date du rapport** : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Total records** : {inv['total']:,}")
    lines.append(f"**Types distincts** : {len(inv['counts'])}")
    lines.append("")

    lines.append(f"## Verdict : **{verdict}**")
    lines.append("")
    for n in notes:
        lines.append(f"- {n}" if n else "")
    lines.append("")

    # Tableau 2 — focus critique (en premier car c'est ce qui compte)
    lines.append("## Tableau 1 — Signaux critiques pour MoodLamp")
    lines.append("")
    lines.append("| Signal | Type Apple | Total | 1ère mesure | Dernière | /jour (30j) | Sources |")
    lines.append("|---|---|---:|---|---|---:|---|")
    for t, label in CRITICAL_TYPES.items():
        n = inv["counts"].get(t, 0)
        if n == 0:
            lines.append(
                f"| {label} | `{short_type(t)}` | **0** | — | — | — | ❌ ABSENT |"
            )
            continue
        lines.append(
            f"| {label} | `{short_type(t)}` | {n:,} "
            f"| {fmt_date(inv['first'].get(t))} "
            f"| {fmt_date(inv['last'].get(t))} "
            f"| {freq_per_day(inv['last_30d'].get(t, 0))} "
            f"| {fmt_sources(inv['sources'].get(t, {}))} |"
        )
    lines.append("")

    # Tableau 1 — tous les types
    lines.append("## Tableau 2 — Tous les types disponibles")
    lines.append("")
    lines.append("| Type | Total | 1ère | Dernière | /jour (30j) | Sources |")
    lines.append("|---|---:|---|---|---:|---|")
    sorted_types = sorted(inv["counts"].items(), key=lambda x: -x[1])
    for t, n in sorted_types:
        lines.append(
            f"| `{short_type(t)}` | {n:,} "
            f"| {fmt_date(inv['first'].get(t))} "
            f"| {fmt_date(inv['last'].get(t))} "
            f"| {freq_per_day(inv['last_30d'].get(t, 0))} "
            f"| {fmt_sources(inv['sources'].get(t, {}))} |"
        )
    lines.append("")

    return "\n".join(lines)


def main():
    if not EXPORT_PATH.exists():
        print(f"❌ Fichier introuvable : {EXPORT_PATH}", file=sys.stderr)
        print("   Place export.xml (issu de l'export Apple Santé) dans data/",
              file=sys.stderr)
        sys.exit(1)

    size_mb = EXPORT_PATH.stat().st_size / 1024 / 1024
    print(f"📂 Parsing {EXPORT_PATH.name} ({size_mb:.1f} Mo)...", file=sys.stderr)

    inv = build_inventory(EXPORT_PATH)
    verdict, notes = compute_verdict(inv)
    md = render_markdown(inv, verdict, notes)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")

    print(md)
    print(f"\n✅ Rapport écrit : {REPORT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
