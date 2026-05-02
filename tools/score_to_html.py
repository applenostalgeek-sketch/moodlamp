#!/usr/bin/env python3
"""
Génère un fichier HTML autonome avec le score + couleur + composantes.

Usage :
  python tools/score_to_html.py
  → ouvre reports/index.html dans ton navigateur

Auto-refresh : la page se recharge toute seule toutes les 60 sec.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from moodlamp import config as cfg
from moodlamp.health_loader import load_or_refresh
from moodlamp.scoring import FormScorer

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "reports" / "index.html"


def color_for_score(score: float, is_asleep: bool) -> tuple[str, str]:
    if is_asleep:
        return cfg.COLOR_SLEEP
    for lo, hi, name, hx in cfg.COLOR_BANDS:
        if lo <= score < hi:
            return name, hx
    last = cfg.COLOR_BANDS[-1]
    return last[2], last[3]


def darken(hex_color: str, amount: float = 0.3) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r * (1 - amount))
    g = int(g * (1 - amount))
    b = int(b * (1 - amount))
    return f"#{r:02x}{g:02x}{b:02x}"


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


def build_html(result, color_name: str, color_hex: str) -> str:
    bg = color_hex
    bg_dark = darken(color_hex, 0.55)
    text_color = "#ffffff"

    weights = cfg.WEIGHTS
    labels = {
        "sleep":     "Sommeil nuit dernière",
        "rhr":       "FC repos vs baseline",
        "load":      "Charge 3 derniers jours",
        "discharge": "Décharge depuis le réveil",
    }

    components_html = ""
    for key in ("sleep", "rhr", "load", "discharge"):
        v = result.components[key]
        w = weights[key]
        contrib = v * w / 100
        components_html += f"""
        <div class="component">
          <div class="component-label">
            <span>{labels[key]}</span>
            <span class="component-value">{v:.0f}/100 × {w}% = {contrib:.1f}</span>
          </div>
          <div class="bar"><div class="bar-fill" style="width: {v:.1f}%"></div></div>
        </div>"""

    # Détails textuels
    s = result.components_detail["sleep"]
    sleep_txt = f"{s.get('hours', 0):.1f}h dont {s.get('deep_pct', 0):.0f}% profond"
    r = result.components_detail["rhr"]
    if r.get("current") is not None:
        rhr_txt = f"{r['current']:.0f} bpm (baseline {r['baseline']:.0f}, écart {r['delta']:+.1f})"
    else:
        rhr_txt = "pas de donnée récente"
    L = result.components_detail["load"]
    load_txt = f"{L['steps_3d']:,} pas + {L['kcal_3d']:,} kcal sur 3j (ratio {L['ratio']:.2f})"
    D = result.components_detail["discharge"]
    discharge_txt = f"{D['minutes_high_hr']} min FC>100 sur {D['since_wake_h']}h éveillé"

    b = result.baseline
    baseline_txt = (f"FC repos {b.rhr_mean:.0f}±{b.rhr_std:.1f} · "
                    f"{b.daily_steps_mean:,.0f} pas/j · "
                    f"{b.daily_kcal_mean:,.0f} kcal/j · "
                    f"{b.sleep_hours_mean:.1f}h sommeil/nuit · "
                    f"{b.n_days} nuits utilisées")

    ts_local = result.timestamp.astimezone()
    ts_str = ts_local.strftime("%A %d %B %Y · %H:%M").lower()

    sleep_badge = ""
    if result.is_asleep:
        ad = result.asleep_detail
        sleep_badge = (
            f'<div class="sleep-badge">💤 sommeil détecté '
            f'(FC {ad["fc_mean_15min"]:.0f} vs baseline {ad["rhr_baseline"]:.0f}, '
            f'{ad["steps_15min"]} pas en 15 min)</div>'
        )

    confidence_badge = ""
    if result.confidence < 0.7:
        confidence_badge = (
            f'<div class="confidence-warn">⚠ confiance {result.confidence*100:.0f}% '
            f'— données pas assez fraîches</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="60">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MoodLamp · {color_name} · {result.score:.0f}/100</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      height: 100%;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                   system-ui, sans-serif;
      background: linear-gradient(135deg, {bg} 0%, {bg_dark} 100%);
      color: {text_color};
      min-height: 100vh;
      padding: 40px 20px;
    }}
    .container {{
      max-width: 720px;
      margin: 0 auto;
    }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      opacity: 0.85;
      font-size: 14px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 60px;
    }}
    .score-block {{
      text-align: center;
      margin-bottom: 50px;
    }}
    .color-name {{
      font-size: 24px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      opacity: 0.9;
      margin-bottom: 16px;
    }}
    .score {{
      font-size: 180px;
      font-weight: 200;
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .score-suffix {{
      font-size: 32px;
      opacity: 0.6;
      margin-left: 8px;
    }}
    .timestamp {{
      margin-top: 12px;
      opacity: 0.7;
      font-size: 14px;
    }}
    .sleep-badge {{
      display: inline-block;
      margin-top: 20px;
      padding: 10px 18px;
      background: rgba(255,255,255,0.2);
      border-radius: 30px;
      font-size: 14px;
    }}
    .confidence-warn {{
      display: inline-block;
      margin-top: 12px;
      padding: 6px 14px;
      background: rgba(0,0,0,0.25);
      border-radius: 4px;
      font-size: 12px;
    }}
    .components {{
      background: rgba(0,0,0,0.18);
      border-radius: 12px;
      padding: 28px;
      margin-bottom: 24px;
    }}
    .components h2 {{
      font-size: 12px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      opacity: 0.7;
      margin-bottom: 20px;
    }}
    .component {{
      margin-bottom: 18px;
    }}
    .component:last-child {{ margin-bottom: 0; }}
    .component-label {{
      display: flex;
      justify-content: space-between;
      font-size: 14px;
      margin-bottom: 6px;
    }}
    .component-value {{
      opacity: 0.75;
      font-variant-numeric: tabular-nums;
    }}
    .bar {{
      height: 8px;
      background: rgba(0,0,0,0.25);
      border-radius: 4px;
      overflow: hidden;
    }}
    .bar-fill {{
      height: 100%;
      background: rgba(255,255,255,0.85);
      transition: width 0.4s ease;
    }}
    .details, .baseline {{
      background: rgba(0,0,0,0.12);
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 16px;
      font-size: 14px;
      line-height: 1.7;
    }}
    .details h2, .baseline h2 {{
      font-size: 12px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      opacity: 0.7;
      margin-bottom: 12px;
    }}
    .details strong {{ font-weight: 600; opacity: 0.9; display: inline-block; min-width: 100px; }}
    .footer {{
      text-align: center;
      margin-top: 30px;
      opacity: 0.5;
      font-size: 11px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <span>MoodLamp</span>
      <span>auto-refresh 60s</span>
    </div>

    <div class="score-block">
      <div class="color-name">{color_name}</div>
      <div class="score">{result.score:.0f}<span class="score-suffix">/100</span></div>
      <div class="timestamp">{ts_str}</div>
      {sleep_badge}
      {confidence_badge}
    </div>

    <div class="components">
      <h2>Composantes du score</h2>
      {components_html}
    </div>

    <div class="details">
      <h2>Détails</h2>
      <div><strong>Sommeil</strong> {sleep_txt}</div>
      <div><strong>FC repos</strong> {rhr_txt}</div>
      <div><strong>Charge 3j</strong> {load_txt}</div>
      <div><strong>Décharge</strong> {discharge_txt}</div>
    </div>

    <div class="baseline">
      <h2>Baseline (60 derniers jours)</h2>
      <div>{baseline_txt}</div>
    </div>

    <div class="footer">
      données : export Apple Santé statique · génération {datetime.now().strftime('%H:%M:%S')}
    </div>
  </div>
</body>
</html>
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--at", type=str, default=None)
    p.add_argument("--refresh", action="store_true",
                   help="Force re-parse de l'XML")
    p.add_argument("--no-open", action="store_true",
                   help="Ne pas ouvrir dans le navigateur")
    args = p.parse_args()

    at = parse_at(args.at)
    data = load_or_refresh(force_refresh=args.refresh)
    scorer = FormScorer(data)
    result = scorer.compute(at=at)

    color_name, color_hex = color_for_score(result.score, result.is_asleep)
    html = build_html(result, color_name, color_hex)

    HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(html, encoding="utf-8")

    print(f"✅ HTML écrit : {HTML_PATH}")
    print(f"   Score {result.score:.0f}/100 — {color_name}"
          + (" 💤" if result.is_asleep else ""))

    if not args.no_open:
        import subprocess
        subprocess.run(["open", str(HTML_PATH)])


if __name__ == "__main__":
    main()
