const KJ_TO_KCAL = 1 / 4.184;

function parseDate(s) {
  if (!s) return null;
  const iso = String(s)
    .replace(" ", "T")
    .replace(/ /g, "")
    .replace(/([+-])(\d{2})(\d{2})$/, "$1$2:$3");
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

export function parseHaePayload(payload) {
  const metrics = payload?.data?.metrics || [];
  const out = {
    heart_rate: [],
    resting_hr: [],
    sleep: [],
    steps: [],
    active_energy: [],
  };

  for (const m of metrics) {
    const data = m.data || [];
    switch (m.name) {
      case "heart_rate":
        for (const d of data) {
          const ts = parseDate(d.date);
          if (!ts) continue;
          const bpm = d.Avg ?? d.qty ?? null;
          if (bpm == null) continue;
          out.heart_rate.push({
            ts: ts.toISOString(),
            bpm: Number(bpm),
            min: d.Min != null ? Number(d.Min) : null,
            max: d.Max != null ? Number(d.Max) : null,
          });
        }
        break;

      case "resting_heart_rate":
        for (const d of data) {
          const ts = parseDate(d.date);
          if (!ts || d.qty == null) continue;
          out.resting_hr.push({
            ts: ts.toISOString(),
            bpm: Number(d.qty),
          });
        }
        break;

      case "step_count":
        for (const d of data) {
          const ts = parseDate(d.date);
          if (!ts || d.qty == null) continue;
          out.steps.push({
            ts: ts.toISOString(),
            count: Number(d.qty),
          });
        }
        break;

      case "active_energy":
        for (const d of data) {
          const ts = parseDate(d.date);
          if (!ts || d.qty == null) continue;
          out.active_energy.push({
            ts: ts.toISOString(),
            kcal: Number(d.qty) * KJ_TO_KCAL,
          });
        }
        break;

      case "sleep_analysis":
        for (const d of data) {
          const sleepStart = parseDate(d.sleepStart);
          const sleepEnd = parseDate(d.sleepEnd);
          if (!sleepStart || !sleepEnd) continue;
          const nightDate = parseDate(d.date) || sleepStart;
          out.sleep.push({
            night_date: nightDate.toISOString().slice(0, 10),
            sleep_start: sleepStart.toISOString(),
            sleep_end: sleepEnd.toISOString(),
            in_bed_start: parseDate(d.inBedStart)?.toISOString() ?? null,
            in_bed_end: parseDate(d.inBedEnd)?.toISOString() ?? null,
            total_sleep_h: Number(d.totalSleep ?? 0),
            deep_h: Number(d.deep ?? 0),
            core_h: Number(d.core ?? 0),
            rem_h: Number(d.rem ?? 0),
            awake_h: Number(d.awake ?? 0),
            source: d.source ?? "",
          });
        }
        break;
    }
  }

  return out;
}
