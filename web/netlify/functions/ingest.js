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

  let payload;
  try {
    payload = await req.json();
  } catch {
    return new Response(JSON.stringify({ error: "invalid JSON" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const enriched = {
    received_at: new Date().toISOString(),
    payload,
  };

  await store.setJSON("last_payload", enriched);

  const summary = {
    received_at: enriched.received_at,
    keys: Object.keys(payload || {}),
    size_bytes: JSON.stringify(payload).length,
  };

  return new Response(JSON.stringify({ status: "ok", ...summary }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

export const config = {
  path: "/api/ingest",
};
