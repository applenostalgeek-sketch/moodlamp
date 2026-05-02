"""
Mini serveur HTTP local pour MoodLamp.

Routes :
  GET  /           → page HTML avec le score actuel
  POST /refresh    → re-parse l'XML (cache invalidé), retourne {"ok": true}
  GET  /api/score  → JSON brut du score (utile pour debug)

Stack : http.server stdlib, zéro dépendance.

Usage :
  python -m moodlamp.server
  → écoute sur http://127.0.0.1:8765
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Imports projet
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from moodlamp import config as cfg
from moodlamp.health_loader import load_or_refresh, EXPORT_PATH
from moodlamp.scoring import FormScorer

# On n'utilise pas 8080 (déjà pris par autre projet de Jo) ni 8081
PORT = 8765
HOST = "127.0.0.1"

# État partagé (chargé au démarrage, rechargé sur /refresh)
_state = {
    "data": None,
    "scorer": None,
    "loaded_at": None,
    "is_refreshing": False,
    "lock": threading.Lock(),
}


def load_data(force_refresh: bool = False):
    """Charge ou recharge les données et met à jour l'état partagé."""
    with _state["lock"]:
        _state["is_refreshing"] = True
    try:
        data = load_or_refresh(force_refresh=force_refresh)
        scorer = FormScorer(data)
        with _state["lock"]:
            _state["data"] = data
            _state["scorer"] = scorer
            _state["loaded_at"] = datetime.now(timezone.utc)
    finally:
        with _state["lock"]:
            _state["is_refreshing"] = False


def color_for_score(score: float, is_asleep: bool) -> tuple[str, str]:
    if is_asleep:
        return cfg.COLOR_SLEEP
    for lo, hi, name, hx in cfg.COLOR_BANDS:
        if lo <= score < hi:
            return name, hx
    last = cfg.COLOR_BANDS[-1]
    return last[2], last[3]


def darken(hex_color: str, amount: float = 0.55) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(r*(1-amount)):02x}{int(g*(1-amount)):02x}{int(b*(1-amount)):02x}"


def freshness_text(data) -> tuple[str, bool]:
    """Renvoie un texte type 'données à jour il y a 23 min' + flag stale."""
    last_hr = data["heart_rate"]["ts"].max() if not data["heart_rate"].empty else None
    if last_hr is None:
        return "aucune donnée FC", True
    age_min = (datetime.now(timezone.utc) - last_hr).total_seconds() / 60
    stale = age_min > 60
    if age_min < 60:
        txt = f"dernière FC il y a {age_min:.0f} min"
    elif age_min < 60 * 24:
        txt = f"dernière FC il y a {age_min/60:.1f} h"
    else:
        txt = f"dernière FC il y a {age_min/60/24:.0f} jours"
    return txt, stale


def render_html(scorer: FormScorer, data) -> str:
    result = scorer.compute()
    color_name, color_hex = color_for_score(result.score, result.is_asleep)
    bg = color_hex
    bg_dark = darken(color_hex)
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

    fresh_txt, is_stale = freshness_text(data)

    sleep_badge = ""
    if result.is_asleep:
        ad = result.asleep_detail
        sleep_badge = (
            f'<div class="badge sleep">💤 sommeil détecté '
            f'(FC {ad["fc_mean_15min"]:.0f} vs baseline {ad["rhr_baseline"]:.0f}, '
            f'{ad["steps_15min"]} pas en 15 min)</div>'
        )

    stale_badge = ""
    if is_stale:
        stale_badge = (
            f'<div class="badge warn">⚠ données pas fraîches — refais '
            f'un export Apple Santé puis clique sur Mettre à jour</div>'
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
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                   system-ui, sans-serif;
      background: linear-gradient(135deg, {bg} 0%, {bg_dark} 100%);
      color: #fff;
      padding: 30px 20px;
    }}
    .container {{ max-width: 720px; margin: 0 auto; }}
    .header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      opacity: 0.85;
      font-size: 13px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 32px;
    }}
    .refresh-btn {{
      background: rgba(0,0,0,0.3);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.3);
      padding: 10px 18px;
      border-radius: 30px;
      font-size: 13px;
      letter-spacing: 0.05em;
      cursor: pointer;
      transition: background 0.2s;
      font-family: inherit;
    }}
    .refresh-btn:hover {{ background: rgba(0,0,0,0.5); }}
    .refresh-btn:disabled {{ opacity: 0.5; cursor: wait; }}
    .score-block {{ text-align: center; margin: 30px 0 40px; }}
    .color-name {{
      font-size: 22px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      opacity: 0.9;
      margin-bottom: 14px;
    }}
    .score {{
      font-size: 160px;
      font-weight: 200;
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .score-suffix {{ font-size: 28px; opacity: 0.6; margin-left: 8px; }}
    .timestamp {{
      margin-top: 10px;
      opacity: 0.75;
      font-size: 13px;
    }}
    .freshness {{
      margin-top: 6px;
      opacity: 0.6;
      font-size: 12px;
    }}
    .badge {{
      display: inline-block;
      margin-top: 14px;
      padding: 8px 16px;
      border-radius: 20px;
      font-size: 13px;
    }}
    .badge.sleep {{ background: rgba(255,255,255,0.2); }}
    .badge.warn {{ background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.3); }}
    .components, .details, .baseline {{
      background: rgba(0,0,0,0.18);
      border-radius: 12px;
      padding: 22px 26px;
      margin-bottom: 16px;
    }}
    .components h2, .details h2, .baseline h2 {{
      font-size: 11px;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      opacity: 0.7;
      margin-bottom: 16px;
    }}
    .component {{ margin-bottom: 16px; }}
    .component:last-child {{ margin-bottom: 0; }}
    .component-label {{
      display: flex;
      justify-content: space-between;
      font-size: 14px;
      margin-bottom: 6px;
    }}
    .component-value {{ opacity: 0.75; font-variant-numeric: tabular-nums; }}
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
    .details, .baseline {{ font-size: 14px; line-height: 1.7; }}
    .details strong {{
      font-weight: 600;
      opacity: 0.9;
      display: inline-block;
      min-width: 100px;
    }}
    .footer {{
      text-align: center;
      margin-top: 24px;
      opacity: 0.5;
      font-size: 11px;
    }}
    .toast {{
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(0,0,0,0.85);
      padding: 12px 20px;
      border-radius: 8px;
      font-size: 13px;
      opacity: 0;
      transition: opacity 0.3s;
      pointer-events: none;
    }}
    .toast.show {{ opacity: 1; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <span>MoodLamp</span>
      <button class="refresh-btn" id="refreshBtn" onclick="refreshData()">
        🔄 Mettre à jour les données
      </button>
    </div>

    <div class="score-block">
      <div class="color-name">{color_name}</div>
      <div class="score">{result.score:.0f}<span class="score-suffix">/100</span></div>
      <div class="timestamp">{ts_str}</div>
      <div class="freshness">{fresh_txt} · confiance {result.confidence*100:.0f}%</div>
      {sleep_badge}
      {stale_badge}
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
      auto-refresh 60s · serveur local · http://{HOST}:{PORT}
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    function showToast(msg) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3000);
    }}

    async function refreshData() {{
      const btn = document.getElementById('refreshBtn');
      btn.disabled = true;
      btn.textContent = '⏳ Re-parse XML…';
      showToast('Re-parsing du fichier export.xml (~30 sec)…');
      try {{
        const r = await fetch('/refresh', {{ method: 'POST' }});
        const j = await r.json();
        if (j.ok) {{
          showToast('✅ Données rechargées. Recharge de la page…');
          setTimeout(() => location.reload(), 800);
        }} else {{
          btn.disabled = false;
          btn.textContent = '🔄 Mettre à jour les données';
          showToast('❌ Erreur : ' + (j.error || 'inconnue'));
        }}
      }} catch (e) {{
        btn.disabled = false;
        btn.textContent = '🔄 Mettre à jour les données';
        showToast('❌ Erreur réseau : ' + e.message);
      }}
    }}
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Logs concis sur stderr
        sys.stderr.write(f"  [{self.command}] {self.path}\n")

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            try:
                if _state["scorer"] is None:
                    load_data(force_refresh=False)
                html = render_html(_state["scorer"], _state["data"])
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, str(e).encode("utf-8"), "text/plain")
            return

        if self.path == "/api/score":
            try:
                result = _state["scorer"].compute()
                payload = {
                    "score": result.score,
                    "components": result.components,
                    "is_asleep": result.is_asleep,
                    "confidence": result.confidence,
                    "timestamp": result.timestamp.isoformat(),
                }
                self._send(200, json.dumps(payload, indent=2).encode("utf-8"),
                           "application/json")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode("utf-8"),
                           "application/json")
            return

        self._send(404, b"Not Found", "text/plain")

    def do_POST(self):
        if self.path == "/refresh":
            try:
                if _state["is_refreshing"]:
                    self._send(429, json.dumps(
                        {"ok": False, "error": "déjà en cours"}
                    ).encode("utf-8"), "application/json")
                    return
                load_data(force_refresh=True)
                self._send(200, json.dumps({"ok": True}).encode("utf-8"),
                           "application/json")
            except Exception as e:
                self._send(500, json.dumps(
                    {"ok": False, "error": str(e)}
                ).encode("utf-8"), "application/json")
            return

        self._send(404, b"Not Found", "text/plain")


def main():
    if not EXPORT_PATH.exists():
        print(f"❌ {EXPORT_PATH} introuvable.", file=sys.stderr)
        sys.exit(1)

    print(f"📂 Chargement initial des données...", file=sys.stderr)
    load_data(force_refresh=False)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"\n🚀 MoodLamp prêt sur {url}", file=sys.stderr)
    print(f"   Ouvre cette URL dans ton navigateur.", file=sys.stderr)
    print(f"   Ctrl+C pour arrêter.\n", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Bye", file=sys.stderr)


if __name__ == "__main__":
    main()
