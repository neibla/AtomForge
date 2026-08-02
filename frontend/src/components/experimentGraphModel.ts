import { formatValue } from "@/lib/utils";
import type {
  DagNode,
  ExperimentBundleResponse,
  ExperimentSpec,
  RunRecordResponse,
} from "@/types";

export type NodeStatus =
  | "COMPLETE"
  | "QUEUED"
  | "RUNNING"
  | "REVIEW"
  | "FAILED"
  | "BLOCKED"
  | "NOT_RUN"
  | "DRAFT";

export interface LayoutNode {
  node: DagNode;
  depth: number;
  x: number;
  y: number;
}

export const NODE_WIDTH = 184;
export const NODE_HEIGHT = 132;

const COLUMN_GAP = 52;
const ROW_GAP = 44;
const GRAPH_PADDING = 36;

export const NODE_META: Record<
  DagNode["type"],
  {
    label: string;
    icon: string;
    accent: string;
    description: string;
    dependencyHint: string;
  }
> = {
  FETCH: {
    label: "Fetch material",
    icon: "↓",
    accent: "#5e8aa0",
    description: "Retrieve a reference structure or dataset.",
    dependencyHint: "Usually an entry node; dependencies are optional.",
  },
  ALLOY: {
    label: "Build alloy",
    icon: "◇",
    accent: "#b3834b",
    description: "Construct a seeded supercell and substitutions.",
    dependencyHint: "Requires exactly one upstream structure.",
  },
  SIMULATE: {
    label: "Simulate",
    icon: "∿",
    accent: "#7f9c83",
    description: "Run a declared atomistic simulation mode.",
    dependencyHint: "Requires exactly one upstream structure.",
  },
  SWEEP: {
    label: "Parameter sweep",
    icon: "↔",
    accent: "#6f94b7",
    description:
      "Run one operation over a declared one-dimensional parameter grid.",
    dependencyHint: "Requires exactly one upstream structure.",
  },
  SCRIPT: {
    label: "Analyze",
    icon: "ƒ",
    accent: "#9a5034",
    description: "Run a project analysis script.",
    dependencyHint: "Can consume zero or more upstream outputs.",
  },
};

export function dependencyIds(node: DagNode): string[] {
  if (!node.depends_on) return [];
  return Array.isArray(node.depends_on) ? node.depends_on : [node.depends_on];
}

export function buildLayout(nodes: DagNode[]): {
  layout: LayoutNode[];
  width: number;
  height: number;
} {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const depthCache = new Map<string, number>();

  function depthFor(nodeId: string, visiting = new Set<string>()): number {
    const cached = depthCache.get(nodeId);
    if (cached !== undefined) return cached;
    if (visiting.has(nodeId)) return 0;
    const node = byId.get(nodeId);
    if (!node) return 0;
    const nextVisiting = new Set(visiting).add(nodeId);
    const depth = dependencyIds(node).reduce(
      (maxDepth, dependency) =>
        Math.max(maxDepth, depthFor(dependency, nextVisiting) + 1),
      0,
    );
    depthCache.set(nodeId, depth);
    return depth;
  }

  const groups = new Map<number, DagNode[]>();
  nodes.forEach((node) => {
    const depth = depthFor(node.id);
    const group = groups.get(depth) ?? [];
    group.push(node);
    groups.set(depth, group);
  });

  const layout: LayoutNode[] = [];
  const maxRows = Math.max(
    ...Array.from(groups.values(), (group) => group.length),
    1,
  );
  for (const [depth, group] of groups) {
    group.forEach((node, row) => {
      layout.push({
        node,
        depth,
        x: GRAPH_PADDING + depth * (NODE_WIDTH + COLUMN_GAP),
        y: GRAPH_PADDING + row * (NODE_HEIGHT + ROW_GAP),
      });
    });
  }

  const maxDepth = layout.reduce(
    (maximum, item) => Math.max(maximum, item.depth),
    0,
  );
  const width = Math.max(
    GRAPH_PADDING * 2 + (maxDepth + 1) * NODE_WIDTH + maxDepth * COLUMN_GAP,
    900,
  );
  if (layout.length === 1) layout[0].x = (width - NODE_WIDTH) / 2;
  return {
    layout,
    width,
    height:
      GRAPH_PADDING * 2 +
      maxRows * NODE_HEIGHT +
      Math.max(maxRows - 1, 0) * ROW_GAP,
  };
}

export function nodeStatus(
  run: RunRecordResponse | null,
  node: DagNode,
  bundle: ExperimentBundleResponse,
): NodeStatus {
  const recorded = bundle.results.node_statuses?.[node.id];
  if (recorded) return recorded as NodeStatus;
  if (bundle.results.errors[node.id]) return "FAILED";
  if (run?.state === "FAILED") return "FAILED";
  if (run?.state === "PARTIAL") return "REVIEW";
  if (run?.state === "QUEUED") return "QUEUED";
  if (run?.state === "RUNNING") return "RUNNING";
  return "COMPLETE";
}

export function statusLabel(status: NodeStatus): string {
  if (status === "COMPLETE") return "Complete";
  if (status === "FAILED") return "Failed";
  if (status === "BLOCKED") return "Blocked";
  if (status === "NOT_RUN") return "Not run";
  if (status === "REVIEW") return "Review";
  if (status === "DRAFT") return "Draft";
  return status[0] + status.slice(1).toLowerCase();
}

export function statusClass(status: NodeStatus): string {
  if (status === "COMPLETE")
    return "border-[#557d61] bg-[#18352a] text-[#a9d4ae]";
  if (status === "FAILED")
    return "border-[#78484d] bg-[#3a252a] text-[#f1a7a1]";
  if (status === "BLOCKED")
    return "border-[#78484d] bg-[#30252a] text-[#d9a4a0]";
  if (status === "NOT_RUN")
    return "border-[#5a6265] bg-[#272f31] text-[#b4c0c0]";
  if (status === "REVIEW")
    return "border-[#846844] bg-[#3a3022] text-[#e7bd7e]";
  if (status === "DRAFT") return "border-[#846844] bg-[#3a3022] text-[#e7bd7e]";
  return "border-[#466372] bg-[#1b313b] text-[#a9cbd5]";
}

function resultForNode(
  bundle: ExperimentBundleResponse,
  nodeId: string,
): Record<string, unknown> | null {
  const result = bundle.script_results?.[nodeId];
  return result && typeof result === "object"
    ? (result as Record<string, unknown>)
    : null;
}

export function metricsForNode(
  bundle: ExperimentBundleResponse,
  nodeId: string,
): Array<[string, string]> {
  const result = resultForNode(bundle, nodeId);
  const localMetrics = result?.metrics;
  if (localMetrics && typeof localMetrics === "object") {
    return Object.entries(
      localMetrics as Record<string, { val?: unknown; unit?: unknown }>,
    )
      .slice(0, 6)
      .map(([name, metric]) => [
        name,
        `${formatValue(metric?.val)} ${metric?.unit ?? ""}`.trim(),
      ]);
  }
  return Object.entries(bundle.results.metrics)
    .filter(([name]) => name.startsWith(`${nodeId}_`))
    .slice(0, 6)
    .map(([name, metric]) => [
      name.slice(nodeId.length + 1),
      `${formatValue(metric.val)} ${metric.unit}`,
    ]);
}

export function defaultNodeParams(
  type: DagNode["type"],
): Record<string, unknown> {
  if (type !== "SWEEP") return {};
  return {
    operation: {
      type: "SIMULATE",
      mode: "single_point",
      params: {},
      trials: 1,
    },
    coordinate: {
      name: "cell_scale",
      label: "Cell linear scale",
      unit: "",
      grid: { start: 0.95, stop: 1.05, step: 0.01 },
    },
    apply: { target: "cell_scale", transform: "identity" },
    max_concurrency: 4,
    failure_policy: "require_all",
  };
}

export function paramsForEditor(node: DagNode): string {
  return JSON.stringify(node.params, null, 2);
}

export function safeSpecCopy(spec: ExperimentSpec): ExperimentSpec {
  return JSON.parse(JSON.stringify(spec)) as ExperimentSpec;
}
