import { store } from "../../lib/storage.js";
import { parseHaePayload } from "../../lib/parser.js";
import { mergeHistory, historyStats } from "../../lib/merge.js";
import { compute } from "../../lib/scoring.js";

const HISTORY_KEY = "history";
const BASELINE_KEY = "baseline";
const SCORE_KEY = "score";
const SCORE_HISTORY_KEY = "score_history";
const LAST_PAYLOAD_KEY = "last_payload";

const SCORE_HISTORY_RETENTION_DAYS = 7;

export default async (req) => {
  const blob = store();

  if (req.method === "GET") {
    const [history, baseline, score, last] = await Promise.all([
      blob.get(HISTORY_KEY, { type: "json" }),
      blob.get(BASELINE_KEY, { type: "json" }),
      blob.get(SCORE_KEY, { type: "json" }),
      blob.get(LAST_PAYLOAD_KEY, { type: "json" }),
    ]);
    return json({
      has_history: !!history,
      history_stats: history ? historyStats(history) : null,
      has_baseline: !!baseline,
      has_score: !!score,
      last_received_at: last?.received_at || null,
    });
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const rawBody = await req.text();
  let parsed = null;
  let parseError = null;
  try {
    parsed = JSON.parse(rawBody);
  } catch (e) {
    parseError = String(e);
  }

  const receivedAt = new Date().toISOString();

  if (!parsed) {
    await blob.setJSON(LAST_PAYLOAD_KEY, {
      received_at: receivedAt,
      body_size_bytes: rawBody.length,
      parse_error: parseError,
    });
    return json({ status: "error", reason: "invalid_json" }, 400);
  }

  const incoming = parseHaePayload(parsed);
  const existing = await blob.get(HISTORY_KEY, { type: "json" });
  const merged = mergeHistory(existing, incoming, 7);
  await blob.setJSON(HISTORY_KEY, merged);

  const baseline = await blob.get(BASELINE_KEY, { type: "json" });
  let scoreResult = null;
  let scoreError = null;
  if (baseline) {
    try {
      scoreResult = compute(merged, baseline);
      await blob.setJSON(SCORE_KEY, scoreResult);

      const prior = (await blob.get(SCORE_HISTORY_KEY, { type: "json" })) || [];
      prior.push({
        ts: scoreResult.timestamp,
        score: scoreResult.score,
        color_hex: scoreResult.color_hex,
        color_name: scoreResult.color_name,
        is_asleep: scoreResult.is_asleep,
      });
      const cutoff = Date.now() - SCORE_HISTORY_RETENTION_DAYS * 24 * 3600 * 1000;
      const trimmed = prior.filter((h) => new Date(h.ts).getTime() >= cutoff);
      await blob.setJSON(SCORE_HISTORY_KEY, trimmed);
    } catch (e) {
      scoreError = String(e);
    }
  }

  await blob.setJSON(LAST_PAYLOAD_KEY, {
    received_at: receivedAt,
    body_size_bytes: rawBody.length,
    incoming_stats: historyStats(incoming),
    history_stats: historyStats(merged),
    has_baseline: !!baseline,
    score: scoreResult ? scoreResult.score : null,
    score_error: scoreError,
  });

  return json({
    status: "ok",
    received_at: receivedAt,
    body_size_bytes: rawBody.length,
    incoming_stats: historyStats(incoming),
    history_stats: historyStats(merged),
    score: scoreResult ? scoreResult.score : null,
    color: scoreResult ? scoreResult.color_name : null,
    has_baseline: !!baseline,
    score_error: scoreError,
  });
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const config = {
  path: "/api/ingest",
};
