export default async (req) => {
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

  const summary = {
    received_at: new Date().toISOString(),
    keys: Object.keys(payload || {}),
    size_bytes: JSON.stringify(payload).length,
  };
  console.log("ingest received:", JSON.stringify(summary));

  return new Response(JSON.stringify({ status: "ok", ...summary }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
};

export const config = {
  path: "/api/ingest",
};
