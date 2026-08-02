import type { RunRecordResponse } from "@/types";

export function upsertRun(
  runs: RunRecordResponse[],
  run: RunRecordResponse,
): RunRecordResponse[] {
  return [
    run,
    ...runs.filter(
      (candidate) => candidate.experiment_id !== run.experiment_id,
    ),
  ];
}

export function removeRun(
  runs: RunRecordResponse[],
  experimentId: string,
): RunRecordResponse[] {
  return runs.filter((run) => run.experiment_id !== experimentId);
}
