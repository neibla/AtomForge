import { describe, expect, test } from "bun:test";

import { fetcher } from "./fetcher";

describe("API fetcher", () => {
  test("turns plain-text proxy failures into readable errors", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response("Internal Server Error", {
        status: 500,
        headers: { "content-type": "text/plain" },
      })) as typeof fetch;

    try {
      await expect(fetcher("/api/experiments/demo")).rejects.toMatchObject({
        message: "Internal Server Error",
        status: 500,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test("uses the API detail for structured failures", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ detail: "Artifact is out of date" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      })) as typeof fetch;

    try {
      await expect(fetcher("/api/experiments/demo")).rejects.toMatchObject({
        message: "Artifact is out of date",
        status: 409,
      });
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
