"""
Pousse vers Netlify :
  - la baseline 60j (calculée depuis l'export Apple Santé)
  - les 7 derniers jours d'historique (au format que /api/ingest accepte
    après parsing — donc déjà normalisé, sleep agrégé par nuit comme HAE)

Usage :
    BASELINE_TOKEN=xxxx python scripts/push_initial.py \
        --url https://zingy-khapse-e6aee4.netlify.app
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from moodlamp.health_loader import load_or_refresh
from moodlamp.scoring import compute_baseline


def _iso(ts) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _series(df, ts_col, value_col, value_key, since):
    """Conversion d'une DataFrame ts/value en liste [{ts, <value_key>}]."""
    if df is None or df.empty:
        return []
    sub = df[df[ts_col] >= since]
    out = []
    for _, row in sub.iterrows():
        out.append({"ts": _iso(row[ts_col]), value_key: float(row[value_col])})
    return out


def _aggregate_sleep(sleep_df, since):
    """
    Apple Health donne du sommeil par phase (AsleepDeep, AsleepCore, etc.).
    HAE et notre scoring JS attendent une nuit pré-agrégée :
        { night_date, sleep_start, sleep_end,
          total_sleep_h, deep_h, core_h, rem_h, awake_h, source }
    On regroupe par "nuit" via un gap > 2h entre sessions.
    """
    if sleep_df is None or sleep_df.empty:
        return []
    df = sleep_df[sleep_df["end"] >= since].copy()
    if df.empty:
        return []
    df = df.sort_values("start").reset_index(drop=True)

    nights = []
    current = []
    last_end = None
    GAP = timedelta(hours=2)

    for _, row in df.iterrows():
        if last_end is None or row["start"] - last_end <= GAP:
            current.append(row)
        else:
            if current:
                nights.append(current)
            current = [row]
        last_end = max(last_end, row["end"]) if last_end else row["end"]
    if current:
        nights.append(current)

    out = []
    for cluster in nights:
        start = min(r["start"] for r in cluster)
        end = max(r["end"] for r in cluster)
        # Phases « endormi »
        asleep_phases = {"AsleepDeep", "AsleepCore", "AsleepREM",
                         "AsleepUnspecified", "Asleep"}
        total_min = sum(r["minutes"] for r in cluster
                        if r["phase"] in asleep_phases)
        deep_min = sum(r["minutes"] for r in cluster if r["phase"] == "AsleepDeep")
        core_min = sum(r["minutes"] for r in cluster if r["phase"] == "AsleepCore")
        rem_min = sum(r["minutes"] for r in cluster if r["phase"] == "AsleepREM")
        awake_min = sum(r["minutes"] for r in cluster if r["phase"] == "Awake")
        # Filtre les "nuits" trop courtes (< 30 min) probablement parasites
        if total_min < 30:
            continue
        out.append({
            "night_date": end.astimezone().date().isoformat(),
            "sleep_start": _iso(start),
            "sleep_end": _iso(end),
            "in_bed_start": None,
            "in_bed_end": None,
            "total_sleep_h": round(total_min / 60, 3),
            "deep_h": round(deep_min / 60, 3),
            "core_h": round(core_min / 60, 3),
            "rem_h": round(rem_min / 60, 3),
            "awake_h": round(awake_min / 60, 3),
            "source": "apple_export",
        })
    return out


def build_payload(history_days: int = 7):
    print("📂 Chargement Apple Santé...", file=sys.stderr)
    data = load_or_refresh()

    now = datetime.now(timezone.utc)
    baseline = compute_baseline(data, now)
    print(f"   {baseline}", file=sys.stderr)

    history_since = now - timedelta(days=history_days)

    history = {
        "heart_rate": [
            {"ts": _iso(row["ts"]), "bpm": float(row["bpm"]),
             "min": None, "max": None}
            for _, row in data["heart_rate"][
                data["heart_rate"]["ts"] >= history_since
            ].iterrows()
        ],
        "resting_hr": _series(data["resting_hr"], "ts", "bpm", "bpm",
                              history_since),
        "steps": _series(data["steps"], "ts", "count", "count", history_since),
        "active_energy": _series(data["active_energy"], "ts", "kcal", "kcal",
                                 history_since),
        "sleep": _aggregate_sleep(data["sleep"], history_since),
    }
    print(
        f"   history: hr={len(history['heart_rate'])} "
        f"rhr={len(history['resting_hr'])} "
        f"steps={len(history['steps'])} "
        f"kcal={len(history['active_energy'])} "
        f"sleep={len(history['sleep'])}", file=sys.stderr)

    return {
        "baseline": {
            "rhr_mean": baseline.rhr_mean,
            "rhr_std": baseline.rhr_std,
            "daily_steps_mean": baseline.daily_steps_mean,
            "daily_kcal_mean": baseline.daily_kcal_mean,
            "sleep_hours_mean": baseline.sleep_hours_mean,
            "n_days": baseline.n_days,
            "computed_at": _iso(now),
        },
        "history": history,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True,
                   help="URL Netlify, ex: https://xxx.netlify.app")
    p.add_argument("--days", type=int, default=7,
                   help="Jours d'historique à pousser (défaut 7)")
    p.add_argument("--dry-run", action="store_true",
                   help="N'envoie pas, écrit le payload dans payload.json")
    args = p.parse_args()

    token = os.environ.get("BASELINE_TOKEN")
    if not token and not args.dry_run:
        print("❌ Variable BASELINE_TOKEN manquante.", file=sys.stderr)
        sys.exit(1)

    payload = build_payload(args.days)
    body = json.dumps(payload).encode("utf-8")
    print(f"📦 Payload: {len(body) / 1024:.1f} KB", file=sys.stderr)

    if args.dry_run:
        out = ROOT / "data" / "push_payload.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2))
        print(f"📝 Écrit dans {out}", file=sys.stderr)
        return

    target = args.url.rstrip("/") + "/api/baseline"
    print(f"📤 POST {target}", file=sys.stderr)
    req = urllib.request.Request(
        target,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Baseline-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"✅ {resp.status}", file=sys.stderr)
            print(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP {e.code}", file=sys.stderr)
        print(e.read().decode("utf-8"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
