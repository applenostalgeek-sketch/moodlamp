const SERIES_KEYS = ["heart_rate", "resting_hr", "steps", "active_energy"];
const SLEEP_KEY = "sleep";

function dedupeByTs(arr) {
  const seen = new Map();
  for (const item of arr) {
    if (!item?.ts) continue;
    seen.set(item.ts, item);
  }
  return Array.from(seen.values()).sort(
    (a, b) => new Date(a.ts) - new Date(b.ts)
  );
}

function dedupeSleep(arr) {
  const seen = new Map();
  for (const item of arr) {
    if (!item?.sleep_start || !item?.sleep_end) continue;
    const key = `${item.sleep_start}|${item.sleep_end}|${item.source || ""}`;
    seen.set(key, item);
  }
  return Array.from(seen.values()).sort(
    (a, b) => new Date(a.sleep_start) - new Date(b.sleep_start)
  );
}

function trimSeries(arr, cutoff) {
  return arr.filter((x) => new Date(x.ts) >= cutoff);
}

function trimSleep(arr, cutoff) {
  return arr.filter((x) => new Date(x.sleep_end) >= cutoff);
}

export function emptyHistory() {
  return {
    heart_rate: [],
    resting_hr: [],
    steps: [],
    active_energy: [],
    sleep: [],
  };
}

export function mergeHistory(existing, incoming, retentionDays = 7) {
  const base = existing || emptyHistory();
  const cutoff = new Date(Date.now() - retentionDays * 24 * 3600 * 1000);
  const out = {};
  for (const k of SERIES_KEYS) {
    const merged = [...(base[k] || []), ...(incoming[k] || [])];
    out[k] = trimSeries(dedupeByTs(merged), cutoff);
  }
  const mergedSleep = [...(base[SLEEP_KEY] || []), ...(incoming[SLEEP_KEY] || [])];
  out[SLEEP_KEY] = trimSleep(dedupeSleep(mergedSleep), cutoff);
  return out;
}

export function historyStats(history) {
  return {
    heart_rate: history.heart_rate?.length || 0,
    resting_hr: history.resting_hr?.length || 0,
    steps: history.steps?.length || 0,
    active_energy: history.active_energy?.length || 0,
    sleep: history.sleep?.length || 0,
  };
}
