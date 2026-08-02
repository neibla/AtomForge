import type { ExperimentBundleResponse, ExperimentSpec } from "@/types";

export function createInitialExperimentBundle(): ExperimentBundleResponse {
  const suffix = new Date()
    .toISOString()
    .replace(/[-:TZ.]/g, "")
    .slice(0, 14);
  const spec: ExperimentSpec = {
    experiment_id: `materials-study-${suffix}`,
    dag: [
      { id: "fetch_structure", type: "FETCH", params: { element: "Si" } },
      {
        id: "relax_structure",
        type: "SIMULATE",
        depends_on: "fetch_structure",
        params: { mode: "relax", trials: 1, fmax: 0.02, steps: 200 },
      },
    ],
    hypotheses: [
      {
        id: "relaxation_converged",
        target_node: "relax_structure",
        metric: "max_force",
        assertion: "target.max_force <= 0.02",
      },
    ],
  };
  return {
    spec,
    results: {
      experiment_id: spec.experiment_id,
      status: "SUCCESS",
      metrics: {},
      hypotheses: [],
      model_info: {},
      node_model_info: {},
      summary: "Draft experiment",
      errors: {},
    },
    scientific_decision: {
      contract_version: "scientific-decision.v1",
      outcome: "BLOCKED",
      calibration: {
        status: "INSUFFICIENT_EVIDENCE",
        accepted_case_count: 0,
        minimum_case_count: 0,
      },
      scope: "Draft experiment; no scientific result has been recorded.",
      headline: "Scientific decision pending experiment execution.",
      supported_claims: [],
      limitations: ["A draft workflow is not scientific evidence."],
      quality_checks: [],
    },
    script_results: {},
  };
}
