import { defineConfig } from "orval";

export default defineConfig({
  atomforge: {
    input: {
      target: ".generated/openapi.json",
    },
    output: {
      mode: "tags-split",
      target: "src/api/generated.ts",
      schemas: "src/api/model",
      client: "react-query",
      httpClient: "fetch",
      baseUrl: "/api",
      override: {
        mutator: {
          path: "./src/api/fetcher.ts",
          name: "fetcher",
        },
        fetch: {
          includeHttpResponseReturnType: false,
        },
      },
    },
  },
});
