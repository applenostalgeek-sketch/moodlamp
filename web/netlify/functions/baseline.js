import { store } from "../../lib/storage.js";

const BASELINE_KEY = "baseline";
const HISTORY_KEY = "history";

export default async (req) => {
  const blob = store();

  if (req.method === "GET") {
    const baseline = await blob.get(BASELINE_KEY, { type: "json" });
    if (!baseline) {
      return json({ has_baseline: false }, 404);
    }
    return json({ has_baseline: true, baseline });
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const expected = process.env.BASELINE_TOKEN;
  if (!expected) {
    return json({ status: "error", reason: "BASELINE_TOKEN not configured" }, 500);
  }
  const provided = req.headers.get("x-baseline-token");
  if (provided !== expected) {
    return json({ status: "error", reason: "unauthorized" }, 401);
  }

  let body;
  try {
    body = await req.json();
  } catch (e) {
    return json({ status: "error", reason: "invalid_json" }, 400);
  }

  const baseline = body.baseline;
  if (!baseline || typeof baseline.rhr_mean !== "number") {
    return json({ status: "error", reason: "missing baseline.rhr_mean" }, 400);
  }

  const normalized = {
    rhr_mean: Number(baseline.rhr_mean),
    rhr_std: Number(baseline.rhr_std ?? 3),
    daily_steps_mean: Number(baseline.daily_steps_mean ?? 8000),
    daily_kcal_mean: Number(baseline.daily_kcal_mean ?? 400),
    sleep_hours_mean: Number(baseline.sleep_hours_mean ?? 7),
    n_days: Number(baseline.n_days ?? 0),
    computed_at: baseline.computed_at || new Date().toISOString(),
  };

  await blob.setJSON(BASELINE_KEY, normalized);

  let initialHistory = null;
  if (body.history && typeof body.history === "object") {
    initialHistory = body.history;
    await blob.setJSON(HISTORY_KEY, initialHistory);
  }

  return json({
    status: "ok",
    baseline: normalized,
    history_seeded: !!initialHistory,
  });
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const config = {
  path: "/api/baseline",
};
