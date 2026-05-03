import { store } from "../../lib/storage.js";
import { compute } from "../../lib/scoring.js";

const HISTORY_KEY = "history";
const BASELINE_KEY = "baseline";
const SCORE_KEY = "score";

export default async (req) => {
  if (req.method !== "GET") {
    return new Response("Method not allowed", { status: 405 });
  }

  const blob = store();
  const url = new URL(req.url);
  const fresh = url.searchParams.get("fresh") === "1";

  const [history, baseline] = await Promise.all([
    blob.get(HISTORY_KEY, { type: "json" }),
    blob.get(BASELINE_KEY, { type: "json" }),
  ]);

  if (!baseline) {
    return json({ status: "error", reason: "no_baseline" }, 404);
  }
  if (!history) {
    return json({ status: "error", reason: "no_history" }, 404);
  }

  if (fresh) {
    const result = compute(history, baseline);
    await blob.setJSON(SCORE_KEY, result);
    return json(result);
  }

  const cached = await blob.get(SCORE_KEY, { type: "json" });
  if (cached) {
    return json(cached);
  }
  const result = compute(history, baseline);
  await blob.setJSON(SCORE_KEY, result);
  return json(result);
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export const config = {
  path: "/api/score",
};
