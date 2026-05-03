import { getStore } from "@netlify/blobs";

export default async (req) => {
  const store = getStore("moodlamp");

  if (req.method === "GET") {
    const last = await store.get("last_payload", { type: "json" });
    return new Response(
      JSON.stringify(
        {
          has_payload: last !== null,
          last_payload: last,
        },
        null,
        2
      ),
      {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const headers = {};
  for (const [k, v] of req.headers.entries()) headers[k] = v;

  const rawBody = await req.text();

  let parsed = null;
  let parseError = null;
  try {
    parsed = JSON.parse(rawBody);
  } catch (e) {
    parseError = String(e);
  }

  const enriched = {
    received_at: new Date().toISOString(),
    method: req.method,
    headers,
    body_size_bytes: rawBody.length,
    body_preview: rawBody.slice(0, 4000),
    parse_error: parseError,
    parsed_keys: parsed && typeof parsed === "object" ? Object.keys(parsed) : null,
    parsed,
  };

  await store.setJSON("last_payload", enriched);

  return new Response(
    JSON.stringify({
      status: "ok",
      received_at: enriched.received_at,
      body_size_bytes: enriched.body_size_bytes,
      content_type: headers["content-type"] || null,
      parsed: parsed !== null,
    }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }
  );
};

export const config = {
  path: "/api/ingest",
};
