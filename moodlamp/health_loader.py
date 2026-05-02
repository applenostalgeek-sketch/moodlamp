"""
Loader des données Apple Santé.

Rôle :
  - Parser export.xml (gros, donc en streaming via iterparse)
  - Pour chaque signal qui nous intéresse, détecter automatiquement la
    "meilleure source" (celle avec le plus d'entrées sur les 90 derniers
    jours) — évite le double-comptage entre "HUAWEI Santé : Europe",
    "HUAWEI Santé", "jo", etc.
  - Sauvegarder le résultat en CSV (rapide à recharger, lisible humain)

Usage :
  from moodlamp.health_loader import load_or_refresh
  data = load_or_refresh()  # dict de DataFrames

  data["heart_rate"]      → DataFrame ts, bpm
  data["resting_hr"]      → DataFrame ts, bpm
  data["sleep"]           → DataFrame start, end, phase, minutes
  data["steps"]           → DataFrame ts, count
  data["active_energy"]   → DataFrame ts, kcal
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EXPORT_PATH = ROOT / "data" / "export.xml"
CACHE_DIR = ROOT / "data" / "cache"

# Signaux qu'on veut extraire et leur identifiant Apple
SIGNALS = {
    "heart_rate":     "HKQuantityTypeIdentifierHeartRate",
    "resting_hr":     "HKQuantityTypeIdentifierRestingHeartRate",
    "sleep":          "HKCategoryTypeIdentifierSleepAnalysis",
    "steps":          "HKQuantityTypeIdentifierStepCount",
    "active_energy":  "HKQuantityTypeIdentifierActiveEnergyBurned",
}

# Inverse pour lookup rapide
TYPE_TO_SIGNAL = {v: k for k, v in SIGNALS.items()}

# Fenêtre pour détecter la "meilleure source" par signal
SOURCE_DETECTION_DAYS = 90


def _parse_apple_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def _detect_best_sources(xml_path: Path) -> dict[str, str]:
    """
    Premier passage : pour chaque signal, compte les entrées par source
    sur les SOURCE_DETECTION_DAYS derniers jours, retient la plus prolifique.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=SOURCE_DETECTION_DAYS)
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    print(f"  [1/2] Détection des meilleures sources "
          f"(fenêtre {SOURCE_DETECTION_DAYS}j)...", file=sys.stderr)

    context = ET.iterparse(str(xml_path), events=("end",))
    for _, elem in context:
        if elem.tag != "Record":
            elem.clear()
            continue
        t = elem.get("type", "")
        signal = TYPE_TO_SIGNAL.get(t)
        if signal is None:
            elem.clear()
            continue
        sd = _parse_apple_date(elem.get("startDate", ""))
        if sd is None or sd < cutoff:
            elem.clear()
            continue
        src = elem.get("sourceName", "")
        counts[signal][src] += 1
        elem.clear()

    best = {}
    for signal, src_counts in counts.items():
        ranked = sorted(src_counts.items(), key=lambda x: -x[1])
        best[signal] = ranked[0][0] if ranked else None
        print(f"      {signal:14s} → {best[signal]}  "
              f"({ranked[0][1]:,} entrées sur {SOURCE_DETECTION_DAYS}j)",
              file=sys.stderr)
        # On signale les sources écartées (transparence)
        for other_src, n in ranked[1:3]:
            print(f"          (écarté : {other_src} — {n:,})",
                  file=sys.stderr)

    return best


def _extract_records(
    xml_path: Path,
    best_sources: dict[str, str],
) -> dict[str, list[dict]]:
    """
    Deuxième passage : extrait les records, en gardant uniquement ceux qui
    viennent de la meilleure source pour leur signal.
    """
    print(f"  [2/2] Extraction des records...", file=sys.stderr)
    records: dict[str, list[dict]] = {sig: [] for sig in SIGNALS}

    context = ET.iterparse(str(xml_path), events=("end",))
    n = 0
    for _, elem in context:
        if elem.tag != "Record":
            elem.clear()
            continue
        t = elem.get("type", "")
        signal = TYPE_TO_SIGNAL.get(t)
        if signal is None:
            elem.clear()
            continue
        src = elem.get("sourceName", "")
        if src != best_sources.get(signal):
            elem.clear()
            continue

        sd = _parse_apple_date(elem.get("startDate", ""))
        ed = _parse_apple_date(elem.get("endDate", ""))
        val = elem.get("value", "")

        if signal == "sleep":
            # value = "HKCategoryValueSleepAnalysisAsleepREM" / Core / Deep ...
            phase = val.replace("HKCategoryValueSleepAnalysis", "")
            duration = (ed - sd).total_seconds() / 60 if ed else 0
            records["sleep"].append({
                "start": sd, "end": ed, "phase": phase, "minutes": duration,
            })
        else:
            try:
                v = float(val)
            except ValueError:
                elem.clear()
                continue
            records[signal].append({"ts": sd, "value": v})

        n += 1
        if n % 100_000 == 0:
            print(f"      ... {n:,} records gardés", file=sys.stderr)
        elem.clear()

    return records


def _to_dataframes(
    records: dict[str, list[dict]],
) -> dict[str, pd.DataFrame]:
    out = {}
    for sig, rows in records.items():
        if not rows:
            out[sig] = pd.DataFrame()
            continue
        df = pd.DataFrame(rows)
        if sig == "sleep":
            df = df.sort_values("start").reset_index(drop=True)
        else:
            df = df.sort_values("ts").reset_index(drop=True)
            df = df.rename(columns={"value": _value_col_name(sig)})
        out[sig] = df
    return out


def _value_col_name(signal: str) -> str:
    return {
        "heart_rate": "bpm",
        "resting_hr": "bpm",
        "steps": "count",
        "active_energy": "kcal",
    }.get(signal, "value")


def _save_cache(data: dict[str, pd.DataFrame], best_sources: dict[str, str]):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for sig, df in data.items():
        path = CACHE_DIR / f"{sig}.csv"
        df.to_csv(path, index=False)
    # Sauvegarde aussi le mapping source pour traçabilité
    meta_path = CACHE_DIR / "sources.txt"
    meta_path.write_text(
        "\n".join(f"{sig} = {src}" for sig, src in best_sources.items())
        + f"\n\ngenerated_at = {datetime.now().isoformat()}\n"
    )


def _load_cache() -> dict[str, pd.DataFrame] | None:
    if not (CACHE_DIR / "sources.txt").exists():
        return None
    out = {}
    for sig in SIGNALS:
        path = CACHE_DIR / f"{sig}.csv"
        if not path.exists():
            return None
        df = pd.read_csv(path)
        # Re-parse les dates
        for col in ("ts", "start", "end"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True)
        out[sig] = df
    return out


def load_or_refresh(force_refresh: bool = False) -> dict[str, pd.DataFrame]:
    """
    Point d'entrée principal.
    - Si un cache existe et force_refresh=False → charge depuis CSV (rapide)
    - Sinon → re-parse l'XML, détecte les sources, sauve le cache
    """
    if not force_refresh:
        cached = _load_cache()
        if cached is not None:
            return cached

    if not EXPORT_PATH.exists():
        raise FileNotFoundError(f"Export Apple Santé introuvable : {EXPORT_PATH}")

    print(f"📂 Refresh du cache depuis {EXPORT_PATH.name}...", file=sys.stderr)
    best_sources = _detect_best_sources(EXPORT_PATH)
    records = _extract_records(EXPORT_PATH, best_sources)
    data = _to_dataframes(records)
    _save_cache(data, best_sources)

    # Résumé
    print("\n📊 Résumé :", file=sys.stderr)
    for sig, df in data.items():
        n = len(df)
        if n == 0:
            print(f"      {sig:14s} → vide", file=sys.stderr)
            continue
        ts_col = "start" if sig == "sleep" else "ts"
        first = df[ts_col].min()
        last = df[ts_col].max()
        print(f"      {sig:14s} → {n:>7,} entrées  "
              f"({first.date()} → {last.date()})", file=sys.stderr)

    return data


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true",
                   help="Force le re-parse de l'XML")
    args = p.parse_args()
    load_or_refresh(force_refresh=args.refresh)
