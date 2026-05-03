export const CONFIG = {
  BASELINE_DAYS: 60,
  WEIGHTS: { sleep: 40, rhr: 30, load: 20, discharge: 10, hrv: 0 },
  SLEEP: {
    duration_excellent: 8.0,
    duration_good: 7.0,
    duration_poor: 5.0,
    duration_terrible: 3.5,
    // Calibré sur la distribution réelle du capteur Huawei (61 nuits) :
    // médiane 28%, p10 18%, p75 35%. Huawei sur-rapporte vs norme médicale
    // (~1.5x), seuils ajustés en conséquence pour préserver le signal.
    deep_target_pct: 35.0,
    deep_min_pct: 18.0,
    duration_weight: 0.65,
    deep_weight: 0.35,
  },
  RHR: { excellent_delta_bpm: -3.0, critical_delta_bpm: 8.0 },
  LOAD: {
    window_days: 3,
    ratio_low: 0.7,
    ratio_normal: 1.0,
    ratio_high: 1.3,
    ratio_overload: 1.6,
  },
  DISCHARGE: {
    high_hr_threshold: 100,
    minutes_low: 15,
    minutes_normal: 45,
    minutes_high: 120,
    minutes_extreme: 240,
  },
  SLEEP_DETECTION: {
    window_minutes: 15,
    max_fc_above_rhr: 5,
    max_steps: 5,
    night_start_hour: 21,
    night_end_hour: 9,
    nap_start_hour: 12,
    nap_end_hour: 17,
  },
  COLOR_BANDS: [
    [0, 30, "rouge", "#c0392b"],
    [30, 50, "orange", "#e67e22"],
    [50, 70, "jaune", "#f1c40f"],
    [70, 100, "vert", "#27ae60"],
  ],
  COLOR_SLEEP: ["bleu", "#2980b9"],
};

function lerp(x, x0, x1, y0, y1) {
  if (x1 === x0) return y0;
  let t = (x - x0) / (x1 - x0);
  t = Math.max(0, Math.min(1, t));
  return y0 + t * (y1 - y0);
}

function piecewise(x, points) {
  if (x <= points[0][0]) return points[0][1];
  if (x >= points[points.length - 1][0]) return points[points.length - 1][1];
  for (let i = 0; i < points.length - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    if (x0 <= x && x <= x1) return lerp(x, x0, x1, y0, y1);
  }
  return points[points.length - 1][1];
}

const round1 = (v) => Math.round(v * 10) / 10;
const round2 = (v) => Math.round(v * 100) / 100;
const sumBy = (arr, fn) => arr.reduce((a, b) => a + (fn(b) || 0), 0);
const meanOf = (arr) => (arr.length ? sumBy(arr, (x) => x) / arr.length : 0);

function inWindow(arr, tsKey, from, to) {
  return arr.filter((x) => {
    const t = new Date(x[tsKey]);
    return t >= from && t <= to;
  });
}

export function scoreSleep(sleepArr, at) {
  if (!sleepArr || !sleepArr.length) {
    return [50, { hours: 0, deep_pct: 0, note: "aucune donnée" }];
  }
  const past = sleepArr
    .filter((s) => new Date(s.sleep_end) < at)
    .sort((a, b) => new Date(b.sleep_end) - new Date(a.sleep_end));
  if (!past.length) {
    return [50, { hours: 0, deep_pct: 0, note: "aucune donnée" }];
  }
  const night = past[0];
  const hours = night.total_sleep_h || 0;
  const deepPct = hours > 0 ? (night.deep_h / hours) * 100 : 0;

  const s = CONFIG.SLEEP;
  const durationScore = piecewise(hours, [
    [s.duration_terrible, 0],
    [s.duration_poor, 25],
    [s.duration_good, 75],
    [s.duration_excellent, 100],
  ]);
  const qualityScore = piecewise(deepPct, [
    [0, 0],
    [s.deep_min_pct, 30],
    [s.deep_target_pct, 100],
  ]);
  const final = durationScore * s.duration_weight + qualityScore * s.deep_weight;

  return [
    final,
    {
      hours: round2(hours),
      deep_pct: round1(deepPct),
      duration_score: round1(durationScore),
      quality_score: round1(qualityScore),
      night_date: night.night_date,
    },
  ];
}

export function scoreRhr(rhrArr, baseline, at) {
  const cutoff = new Date(at.getTime() - 36 * 3600 * 1000);
  const recent = inWindow(rhrArr || [], "ts", cutoff, at).sort(
    (a, b) => new Date(a.ts) - new Date(b.ts)
  );

  if (!recent.length) {
    return [
      50,
      {
        current: null,
        baseline: round1(baseline.rhr_mean),
        delta: null,
        note: "pas de FC repos récente",
      },
    ];
  }
  const current = recent[recent.length - 1].bpm;
  const delta = current - baseline.rhr_mean;
  const r = CONFIG.RHR;
  const score = piecewise(delta, [
    [r.excellent_delta_bpm, 100],
    [0, 50],
    [r.critical_delta_bpm, 0],
  ]);
  return [
    score,
    {
      current: round1(current),
      baseline: round1(baseline.rhr_mean),
      delta: round1(delta),
    },
  ];
}

export function scoreLoad(stepsArr, kcalArr, baseline, at) {
  const window = CONFIG.LOAD.window_days * 24 * 3600 * 1000;
  const cutoff = new Date(at.getTime() - window);
  const sFiltered = inWindow(stepsArr || [], "ts", cutoff, at);
  const kFiltered = inWindow(kcalArr || [], "ts", cutoff, at);

  const stepsTotal = sumBy(sFiltered, (x) => x.count);
  const kcalTotal = sumBy(kFiltered, (x) => x.kcal);

  const expectedSteps = baseline.daily_steps_mean * CONFIG.LOAD.window_days;
  const expectedKcal = baseline.daily_kcal_mean * CONFIG.LOAD.window_days;

  let ratio;
  if (expectedSteps > 0 && expectedKcal > 0) {
    ratio = 0.5 * (stepsTotal / expectedSteps + kcalTotal / expectedKcal);
  } else if (expectedSteps > 0) {
    ratio = stepsTotal / expectedSteps;
  } else {
    ratio = 1.0;
  }

  const L = CONFIG.LOAD;
  const score = piecewise(ratio, [
    [L.ratio_low, 90],
    [L.ratio_normal, 70],
    [L.ratio_high, 40],
    [L.ratio_overload, 0],
  ]);

  return [
    score,
    {
      steps_3d: Math.round(stepsTotal),
      kcal_3d: Math.round(kcalTotal),
      expected_steps_3d: Math.round(expectedSteps),
      expected_kcal_3d: Math.round(expectedKcal),
      ratio: round2(ratio),
    },
  ];
}

export function scoreDischarge(hrArr, sleepArr, at) {
  let wake = null;
  if (sleepArr && sleepArr.length) {
    const past = sleepArr
      .filter((s) => new Date(s.sleep_end) < at)
      .sort((a, b) => new Date(b.sleep_end) - new Date(a.sleep_end));
    if (past.length) wake = new Date(past[0].sleep_end);
  }
  if (!wake) {
    wake = new Date(at);
    wake.setHours(6, 0, 0, 0);
    if (wake > at) wake = new Date(wake.getTime() - 24 * 3600 * 1000);
  }

  const awakeHr = inWindow(hrArr || [], "ts", wake, at);
  if (!awakeHr.length) {
    return [
      70,
      {
        minutes_high_hr: 0,
        since_wake_h: 0,
        note: "pas de FC depuis le réveil",
      },
    ];
  }
  const threshold = CONFIG.DISCHARGE.high_hr_threshold;
  const highCount = awakeHr.filter((h) => h.bpm > threshold).length;

  const D = CONFIG.DISCHARGE;
  const score = piecewise(highCount, [
    [D.minutes_low, 90],
    [D.minutes_normal, 60],
    [D.minutes_high, 20],
    [D.minutes_extreme, 0],
  ]);
  return [
    score,
    {
      minutes_high_hr: highCount,
      since_wake_h: round1((at - wake) / 3600000),
    },
  ];
}

export function detectAsleep(hrArr, stepsArr, baseline, at) {
  const SD = CONFIG.SLEEP_DETECTION;
  const cutoff = new Date(at.getTime() - SD.window_minutes * 60 * 1000);
  const recentHr = inWindow(hrArr || [], "ts", cutoff, at);
  const recentSteps = inWindow(stepsArr || [], "ts", cutoff, at);

  if (!recentHr.length) {
    return [false, { reason: "pas de FC récente" }];
  }
  const fcMean = meanOf(recentHr.map((h) => h.bpm));
  const stepsTotal = sumBy(recentSteps, (x) => x.count);
  const localHour = new Date(at).getHours();

  const isNight =
    localHour >= SD.night_start_hour || localHour < SD.night_end_hour;
  const isNapWindow =
    SD.nap_start_hour <= localHour && localHour < SD.nap_end_hour;
  const fcLow = fcMean <= baseline.rhr_mean + SD.max_fc_above_rhr;
  const immobile = stepsTotal <= SD.max_steps;
  const plausible = isNight || isNapWindow;
  const asleep = fcLow && immobile && plausible;

  return [
    asleep,
    {
      fc_mean_15min: round1(fcMean),
      rhr_baseline: round1(baseline.rhr_mean),
      steps_15min: Math.round(stepsTotal),
      local_hour: localHour,
      is_night: isNight,
      is_nap_window: isNapWindow,
      fc_low: fcLow,
      immobile,
    },
  ];
}

export function colorForScore(score, isAsleep) {
  if (isAsleep) return CONFIG.COLOR_SLEEP;
  for (const [lo, hi, name, hex] of CONFIG.COLOR_BANDS) {
    if (lo <= score && score < hi) return [name, hex];
  }
  const last = CONFIG.COLOR_BANDS[CONFIG.COLOR_BANDS.length - 1];
  return [last[2], last[3]];
}

export function compute(history, baseline, at = null) {
  if (!at) at = new Date();
  if (!(at instanceof Date)) at = new Date(at);

  const [sleepScore, sleepDet] = scoreSleep(history.sleep, at);
  const [rhrScore, rhrDet] = scoreRhr(history.resting_hr, baseline, at);
  const [loadScore, loadDet] = scoreLoad(
    history.steps,
    history.active_energy,
    baseline,
    at
  );
  const [dischargeScore, dischargeDet] = scoreDischarge(
    history.heart_rate,
    history.sleep,
    at
  );

  const components = {
    sleep: sleepScore,
    rhr: rhrScore,
    load: loadScore,
    discharge: dischargeScore,
  };

  const totalW = Object.keys(components).reduce(
    (a, k) => a + (CONFIG.WEIGHTS[k] || 0),
    0
  );
  const score =
    totalW === 0
      ? 50
      : Object.entries(components).reduce(
          (a, [k, v]) => a + v * (CONFIG.WEIGHTS[k] || 0),
          0
        ) / totalW;

  const [isAsleep, asleepDet] = detectAsleep(
    history.heart_rate,
    history.steps,
    baseline,
    at
  );

  let confidence = 0;
  const hr = history.heart_rate || [];
  if (hr.length) {
    const lastHrTs = hr.reduce(
      (max, h) => Math.max(max, new Date(h.ts).getTime()),
      0
    );
    const ageH = (at.getTime() - lastHrTs) / 3600000;
    if (ageH <= 0.5) confidence = 1.0;
    else if (ageH <= 2) confidence = 0.85;
    else if (ageH <= 12) confidence = 0.6;
    else confidence = 0.3;
  }

  const [colorName, colorHex] = colorForScore(score, isAsleep);

  return {
    score: round1(score),
    color_name: colorName,
    color_hex: colorHex,
    components: Object.fromEntries(
      Object.entries(components).map(([k, v]) => [k, round1(v)])
    ),
    components_detail: {
      sleep: sleepDet,
      rhr: rhrDet,
      load: loadDet,
      discharge: dischargeDet,
    },
    is_asleep: isAsleep,
    asleep_detail: asleepDet,
    baseline,
    timestamp: at.toISOString(),
    confidence,
  };
}
