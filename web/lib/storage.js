import { getStore } from "@netlify/blobs";

const STORE_NAME = "moodlamp";

export function store() {
  return getStore(STORE_NAME);
}

export async function readBlob(key) {
  return await store().get(key, { type: "json" });
}

export async function writeBlob(key, value) {
  return await store().setJSON(key, value);
}
