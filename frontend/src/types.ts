export type DashboardView =
  | "graph"
  | "visualization"
  | "report"
  | "configuration";
export type ColorMode = "element" | "energy" | "defect";

export type {
  AtomisticVisualization,
  AtomisticVisualizationData,
  ChartVisualization,
  DagNode,
  ExperimentBundleResponse,
  ExperimentResultsResponse,
  ExperimentSpec,
  HypothesisEval,
  ImageVisualization,
  MetricResult,
  ModelMetadata,
  PKAFrameMetric,
  RunRecordResponse,
  ScientificDecision,
  ScientificQualityCheck,
  SweepResult,
  TableVisualization,
  VisualizationCatalog,
} from "@/api/model";

export type VisualizationValue = string | number | boolean | null;
export type VisualizationSpec = NonNullable<
  import("@/api/model").VisualizationCatalog["visualizations"]
>[number];
