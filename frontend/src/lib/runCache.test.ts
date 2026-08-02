import { describe, expect, it } from "bun:test";

import { removeRun, upsertRun } from "./runCache";
import type { RunRecordResponse } from "../types";

const first: RunRecordResponse = {
  experiment_id: "first",
  state: "SUCCESS",
  created_at: "2026-07-30T00:00:00Z",
  updated_at: "2026-07-30T00:00:00Z",
  revision: 0,
};

const second: RunRecordResponse = {
  ...first,
  experiment_id: "second",
};

describe("run cache updates", () => {
  it("adds a submitted run immediately and replaces stale copies", () => {
    const queued = { ...second, state: "QUEUED" as const };

    expect(upsertRun([first, second], queued)).toEqual([queued, first]);
  });

  it("removes a deleted run immediately", () => {
    expect(removeRun([first, second], "first")).toEqual([second]);
  });
});
