import { useMemo } from "react";
import { CircleDot } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  formatSweepRange,
  formatSweepSummary,
  sweepPresentation,
} from "@/lib/sweeps";
import { nodeTitle } from "@/lib/experimentPresentation";
import type {
  DagNode,
  ExperimentBundleResponse,
  RunRecordResponse,
} from "@/types";

import {
  buildLayout,
  dependencyIds,
  NODE_HEIGHT,
  NODE_META,
  NODE_WIDTH,
  nodeStatus,
  statusClass,
  statusLabel,
  type LayoutNode,
  type NodeStatus,
} from "./experimentGraphModel";

function GraphNodeCard({
  item,
  status,
  selected,
  onSelect,
}: {
  item: LayoutNode;
  status: NodeStatus;
  selected: boolean;
  onSelect: () => void;
}) {
  const meta = NODE_META[item.node.type];
  const sweep = sweepPresentation(item.node);
  return (
    <button
      type="button"
      aria-label={`Select ${item.node.id}: ${sweep ? formatSweepSummary(sweep) : meta.description}`}
      aria-pressed={selected}
      onClick={onSelect}
      className={cn(
        "absolute flex h-[132px] w-[184px] flex-col justify-between rounded-xl border p-3 text-left shadow-[0_12px_30px_rgba(0,0,0,0.18)] transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#d5794f]",
        selected
          ? "border-[#d5794f] bg-[#553023] shadow-[0_0_0_2px_rgba(213,121,79,0.16),0_18px_36px_rgba(0,0,0,0.26)]"
          : "border-[#35515e] bg-[#13262f] hover:border-[#6f8991] hover:bg-[#19313b]",
      )}
      style={{ left: item.x, top: item.y }}
    >
      <span className="flex items-start justify-between gap-2">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-lg text-sm font-semibold"
          style={{ backgroundColor: `${meta.accent}24`, color: meta.accent }}
        >
          {meta.icon}
        </span>
        <span className="data-value text-[10px] text-[#93a8ad]">
          {String(item.depth + 1).padStart(2, "0")}
        </span>
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[12px] font-semibold text-[#f0f5f1]">
          {nodeTitle(item.node.id)}
        </span>
        {sweep ? (
          <>
            <span className="mt-1 block truncate text-[10px] font-semibold text-[#c6d3d1]">
              Parameter · {sweep.label}
            </span>
            <span
              className="mt-1 block truncate font-mono text-[9px] text-[#b9d0dd]"
              title={formatSweepSummary(sweep)}
            >
              {formatSweepRange(sweep)} · {sweep.sampleCount} samples
            </span>
          </>
        ) : (
          <>
            <span className="mt-1 block truncate text-[10px] font-semibold text-[#c6d3d1]">
              {meta.label}
            </span>
            <span
              className="mt-1 block line-clamp-2 text-[10px] leading-tight text-[#91a5ad]"
              title={meta.description}
            >
              {meta.description}
            </span>
          </>
        )}
      </span>
      <span
        className="truncate text-[9px] text-[#78919a]"
        title={sweep ? `${sweep.operationLabel} · ${sweep.targetLabel}` : undefined}
      >
        {sweep
          ? `${sweep.operationLabel} · ${sweep.targetLabel}`
          : dependencyIds(item.node).length
            ? `${dependencyIds(item.node).length} upstream`
            : "Entry node"}
      </span>
      <span
        className={cn(
          "flex w-fit items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em]",
          statusClass(status),
        )}
      >
        <CircleDot className="h-2.5 w-2.5" /> {statusLabel(status)}
      </span>
    </button>
  );
}

export function ExperimentGraphView({
  bundle,
  run,
  nodes,
  selectedId,
  onSelect,
  editing,
}: {
  bundle: ExperimentBundleResponse;
  run: RunRecordResponse | null;
  nodes: DagNode[];
  selectedId: string;
  onSelect: (id: string) => void;
  editing: boolean;
}) {
  const { layout, width, height } = useMemo(() => buildLayout(nodes), [nodes]);
  const positions = new Map(layout.map((item) => [item.node.id, item]));
  const edgeCount = nodes.reduce(
    (count, node) => count + dependencyIds(node).length,
    0,
  );

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="mx-4 mb-0 mt-4 flex shrink-0 items-center justify-between gap-3 rounded-lg border border-[#263f49] bg-[#0d1920] px-3 py-2 font-mono text-[10px] text-[#91a5ad] lg:mx-7 lg:mt-7">
        <span>
          {nodes.length} nodes · {edgeCount} dependency{" "}
          {edgeCount === 1 ? "edge" : "edges"}
        </span>
        <span className="shrink-0 text-[9px] uppercase tracking-[0.1em] text-[#6f8991]">
          Scroll to explore
        </span>
      </div>
      <div
        className="custom-scrollbar graph-canvas min-h-0 min-w-0 flex-1 overflow-auto overscroll-contain p-4 lg:p-7"
        aria-label="Scrollable experiment graph"
      >
        <div
          className="relative min-w-[900px] rounded-2xl border border-[#1e3b46] bg-[#0b1820] shadow-[inset_0_0_70px_rgba(10,45,55,0.16)]"
          style={{ width, height }}
        >
          <div
            className="pointer-events-none absolute inset-0 opacity-30"
            style={{
              backgroundImage:
                "radial-gradient(#54717c 0.8px, transparent 0.8px)",
              backgroundSize: "22px 22px",
            }}
          />
          <svg
            className="pointer-events-none absolute inset-0"
            width={width}
            height={height}
            aria-hidden="true"
          >
            <defs>
              <marker
                id="atomforge-arrow"
                markerWidth="7"
                markerHeight="7"
                refX="6"
                refY="3.5"
                orient="auto"
              >
                <path d="M0,0 L7,3.5 L0,7 z" fill="#6e8991" />
              </marker>
            </defs>
            {layout.flatMap((item) =>
              dependencyIds(item.node).map((dependency) => {
                const source = positions.get(dependency);
                if (!source) return null;
                const startX = source.x + NODE_WIDTH;
                const startY = source.y + NODE_HEIGHT / 2;
                const endX = item.x;
                const endY = item.y + NODE_HEIGHT / 2;
                const bend = Math.max(28, (endX - startX) / 2);
                return (
                  <path
                    key={`${dependency}-${item.node.id}`}
                    d={`M ${startX} ${startY} C ${startX + bend} ${startY}, ${endX - bend} ${endY}, ${endX} ${endY}`}
                    fill="none"
                    stroke="#5d7780"
                    strokeWidth="1.6"
                    markerEnd="url(#atomforge-arrow)"
                  />
                );
              }),
            )}
          </svg>
          {layout.map((item) => (
            <GraphNodeCard
              key={item.node.id}
              item={item}
              status={editing ? "DRAFT" : nodeStatus(run, item.node, bundle)}
              selected={item.node.id === selectedId}
              onSelect={() => onSelect(item.node.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
