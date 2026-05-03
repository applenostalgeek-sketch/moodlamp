import { store } from "../../lib/storage.js";
import { compute, seedScoreHistory } from "../../lib/scoring.js";

const HISTORY_KEY = "history";
const BASELINE_KEY = "baseline";
const SCORE_KEY = "score";
const SCORE_HISTORY_KEY = "score_history";

export default async (req) => {
  if (req.method !== "GET") {
    return new Response("Method not allowed", { status: 405 });
  }

  const blob = store();
  const url = new URL(req.url);
  const fresh = url.searchParams.get("fresh") === "1";

  const [history, baseline, lastPayload] = await Promise.all([
    blob.get(HISTORY_KEY, { type: "json" }),
    blob.get(BASELINE_KEY, { type: "json" }),
    blob.get("last_payload", { type: "json" }),
  ]);

  if (!baseline) {
    return json({ status: "error", reason: "no_baseline" }, 404);
  }
  if (!history) {
    return json({ status: "error", reason: "no_history" }, 404);
  }

  const lastPushAt = lastPayload?.received_at || null;

  let scoreHistory = await blob.get(SCORE_HISTORY_KEY, { type: "json" });
  if (!scoreHistory || scoreHistory.length === 0) {
    scoreHistory = seedScoreHistory(history, baseline, 168, 1);
    await blob.setJSON(SCORE_HISTORY_KEY, scoreHistory);
  }

  let result;
  if (fresh) {
    result = compute(history, baseline);
    await blob.setJSON(SCORE_KEY, result);
  } else {
    const cached = await blob.get(SCORE_KEY, { type: "json" });
    result = cached || compute(history, baseline);
    if (!cached) await blob.setJSON(SCORE_KEY, result);
  }

  result.last_push_at = lastPushAt;
  result.score_history = scoreHistory;
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
