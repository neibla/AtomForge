import { useState } from "react";
import {
  Check,
  Info,
  Play,
  Plus,
  RotateCcw,
  Save,
  X,
} from "lucide-react";

import {
  useCreateExperiment,
  useGetSweepResults,
} from "@/api/default/default";
import { errorMessage } from "@/lib/utils";
import { experimentTitle } from "@/lib/experimentPresentation";
import type {
  DagNode,
  ExperimentBundleResponse,
  ExperimentSpec,
  RunRecordResponse,
} from "@/types";

import {
  defaultNodeParams,
  dependencyIds,
  NODE_META,
  safeSpecCopy,
} from "./experimentGraphModel";
import {
  ExperimentNodeEditor,
  ExperimentNodeInspector,
} from "./experimentInspectors";
import { ExperimentGraphView } from "./experimentGraphView";

type GraphMode = "view" | "edit";

interface ExperimentGraphWorkspaceProps {
  bundle: ExperimentBundleResponse;
  run: RunRecordResponse | null;
  onSubmitted: (run: RunRecordResponse) => void;
  newExperiment?: boolean;
  onClose?: () => void;
}

const STRUCTURAL_NODE_TYPES = new Set<DagNode["type"]>([
  "ALLOY",
  "SIMULATE",
  "SWEEP",
]);

function validateDraftNode(
  node: DagNode,
  seenIds: Set<string>,
  nodeIds: Set<string>,
): string | null {
  if (!node.id.trim()) return "Every node needs an id.";
  if (seenIds.has(node.id)) return `Node id '${node.id}' is duplicated.`;
  seenIds.add(node.id);

  const dependencies = dependencyIds(node);
  for (const dependency of dependencies) {
    if (!nodeIds.has(dependency)) {
      return `Node '${node.id}' references missing dependency '${dependency}'.`;
    }
    if (dependency === node.id)
      return `Node '${node.id}' cannot depend on itself.`;
  }
  if (STRUCTURAL_NODE_TYPES.has(node.type) && dependencies.length !== 1) {
    return `${node.type} node '${node.id}' requires exactly one upstream dependency.`;
  }
  return null;
}

function hasCycle(dag: DagNode[]): boolean {
  const byId = new Map(dag.map((node) => [node.id, node]));
  const visiting = new Set<string>();
  const visited = new Set<string>();

  function visit(id: string): boolean {
    if (visiting.has(id)) return true;
    if (visited.has(id)) return false;
    const node = byId.get(id);
    if (!node) return false;

    visiting.add(id);
    for (const dependency of dependencyIds(node)) {
      if (visit(dependency)) return true;
    }
    visiting.delete(id);
    visited.add(id);
    return false;
  }

  return dag.some((node) => visit(node.id));
}

export function ExperimentGraphWorkspace({
  bundle,
  run,
  onSubmitted,
  newExperiment = false,
  onClose,
}: ExperimentGraphWorkspaceProps) {
  const createMutation = useCreateExperiment();
  const sweepQuery = useGetSweepResults(bundle.spec.experiment_id, {
    query: { enabled: !newExperiment && bundle.sweep_results_ref != null },
  });
  const [mode, setMode] = useState<GraphMode>(newExperiment ? "edit" : "view");
  const [selectedId, setSelectedId] = useState(bundle.spec.dag[0]?.id ?? "");
  const [draft, setDraft] = useState(() => safeSpecCopy(bundle.spec));
  const [draftResetToken, setDraftResetToken] = useState(0);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [editorError, setEditorError] = useState<string | null>(null);
  const [isQueueing, setIsQueueing] = useState(false);

  const activeSpec = mode === "edit" ? draft : bundle.spec;
  const selectedNode =
    activeSpec.dag.find((node) => node.id === selectedId) ?? activeSpec.dag[0];

  function selectNode(id: string) {
    setSelectedId(id);
    setEditorError(null);
  }

  function addNode(type: DagNode["type"]) {
    const base = type.toLowerCase();
    let id = base;
    let index = 2;
    while (draft.dag.some((node) => node.id === id)) id = `${base}_${index++}`;
    setDraft({
      ...draft,
      dag: [
        ...draft.dag,
        { id, type, depends_on: null, params: defaultNodeParams(type) },
      ],
    });
    selectNode(id);
  }

  function updateDraft(next: ExperimentSpec) {
    setDraftError(null);
    setDraft(next);
  }

  function removeSelected() {
    if (!selectedNode) return;
    const remaining = activeSpec.dag
      .filter((node) => node.id !== selectedNode.id)
      .map((node) => {
        const dependencies = dependencyIds(node).filter(
          (dependency) => dependency !== selectedNode.id,
        );
        return {
          ...node,
          depends_on: dependencies.length ? dependencies : null,
        };
      });
    setDraft({
      ...draft,
      dag: remaining,
      decision_node_id:
        draft.decision_node_id === selectedNode.id
          ? null
          : draft.decision_node_id,
    });
    selectNode(remaining[0]?.id ?? "");
  }

  function validateDraft(): string | null {
    if (editorError) return editorError;
    if (!draft.experiment_id.trim()) return "Experiment id is required.";
    if (!draft.dag.length) return "Add at least one node before queueing.";

    const ids = new Set<string>();
    const nodeIds = new Set(draft.dag.map((node) => node.id));
    for (const node of draft.dag) {
      const error = validateDraftNode(node, ids, nodeIds);
      if (error) return error;
    }

    return hasCycle(draft.dag)
      ? "The graph contains a cycle. Remove one dependency before queueing."
      : null;
  }

  async function queueDraft() {
    const error = validateDraft();
    if (error) {
      setDraftError(error);
      return;
    }
    setIsQueueing(true);
    setDraftError(null);
    try {
      const nextRun = await createMutation.mutateAsync({ data: draft });
      onSubmitted(nextRun);
      setMode("view");
    } catch (queueError) {
      setDraftError(errorMessage(queueError, "Queueing failed"));
    } finally {
      setIsQueueing(false);
    }
  }

  return (
    <div className="graph-workspace flex h-full min-h-0 flex-col bg-[#101a20] text-[#dce7e4]">
      <header className="flex flex-wrap items-center gap-3 border-b border-[#30464f] bg-[#101d24] px-5 py-4 lg:px-7">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#d5794f]">
            {newExperiment ? "New experiment" : "Experiment graph"}
          </p>
          <h3 className="mt-1 truncate text-lg font-semibold text-[#f2f7f4]">
            {experimentTitle(activeSpec.experiment_id)}
          </h3>
          <p className="mt-1 text-xs text-[#91a5ad]">
            {activeSpec.dag.length} nodes ·{" "}
            {mode === "edit" ? "draft topology" : "recorded workflow"}
          </p>
          <p className="mt-1 truncate font-mono text-[9px] text-[#70868f]">
            {activeSpec.experiment_id}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onClose ? (
            <button
              type="button"
              aria-label="Close experiment editor"
              onClick={onClose}
              className="rounded-lg p-2 text-[#a7b4b3] transition hover:bg-[#243740] hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
          {newExperiment ? (
            <span className="rounded-md border border-[#846844] bg-[#3a3022] px-3 py-1.5 text-xs font-semibold text-[#e7bd7e]">
              Draft editor
            </span>
          ) : null}
        </div>
      </header>

      {mode === "edit" ? (
        <div className="flex flex-wrap items-center gap-2 border-b border-[#30464f] bg-[#0d1920] px-5 py-3 lg:px-7">
          <span className="mr-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Add node
          </span>
          {(Object.keys(NODE_META) as DagNode["type"][]).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => addNode(type)}
              className="flex items-center gap-1.5 rounded-md border border-[#466372] px-2.5 py-1.5 text-[11px] font-semibold text-[#dce7e4] hover:border-[#d5794f] hover:text-[#ffd5bd]"
            >
              <Plus className="h-3 w-3" /> {type}
            </button>
          ))}
          <span className="ml-auto flex items-center gap-1.5 text-[10px] text-[#d8a867]">
            <Info className="h-3.5 w-3.5" /> Select a node, then choose its
            upstream dependencies in the inspector. Nothing is created until you
            submit the draft.
          </span>
        </div>
      ) : null}

      <div className="min-w-0 min-h-0 flex-1 lg:grid lg:grid-cols-[minmax(0,1fr)_22rem]">
        <ExperimentGraphView
          bundle={bundle}
          run={run}
          nodes={activeSpec.dag}
          selectedId={selectedId}
          onSelect={selectNode}
          editing={mode === "edit"}
        />
        {selectedNode ? (
          mode === "edit" ? (
            <ExperimentNodeEditor
              key={`${selectedNode.id}-${draftResetToken}`}
              draft={draft}
              selectedId={selectedNode.id}
              onChange={updateDraft}
              onValidityChange={setEditorError}
              onSelectedIdChange={selectNode}
              onDelete={removeSelected}
              onClose={() => setMode("view")}
            />
          ) : (
            <ExperimentNodeInspector
              bundle={bundle}
              run={run}
              node={selectedNode}
              sweepResult={
                selectedNode.type === "SWEEP"
                  ? (sweepQuery.data?.results[selectedNode.id] ?? null)
                  : null
              }
              sweepLoading={
                selectedNode.type === "SWEEP" && sweepQuery.isLoading
              }
              sweepError={
                selectedNode.type === "SWEEP" && sweepQuery.error
                  ? errorMessage(
                      sweepQuery.error,
                      "Sweep evidence request failed",
                    )
                  : null
              }
            />
          )
        ) : null}
      </div>

      <footer className="flex flex-wrap items-center gap-4 border-t border-[#30464f] bg-[#101d24] px-5 py-3 lg:px-7">
        <div className="flex items-center gap-3 text-[11px] text-[#a7b4b3]">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#79c28a]" /> Complete
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#d8a867]" /> Review
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#d8a867]" /> Draft
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#6f9aac]" /> Queued
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {draftError ? (
            <span className="max-w-sm text-right text-[11px] text-[#e18d87]">
              {draftError}
            </span>
          ) : null}
          {mode === "edit" ? (
            <>
              <button
                type="button"
                onClick={() => {
                  setDraft(safeSpecCopy(bundle.spec));
                  setDraftError(null);
                  setEditorError(null);
                  setDraftResetToken((token) => token + 1);
                }}
                className="flex items-center gap-1.5 rounded-lg border border-[#466372] px-3 py-2 text-xs font-semibold text-[#c4d2d5] hover:border-[#6d8993] hover:text-white"
              >
                <RotateCcw className="h-3.5 w-3.5" /> Reset
              </button>
              <button
                type="button"
                onClick={() => void queueDraft()}
                disabled={isQueueing}
                className="flex items-center gap-1.5 rounded-lg bg-[#ae5635] px-4 py-2 text-xs font-semibold text-white hover:bg-[#c66b45] disabled:cursor-wait disabled:opacity-60"
              >
                {isQueueing ? (
                  <Save className="h-3.5 w-3.5 animate-pulse" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}{" "}
                Create experiment
              </button>
            </>
          ) : (
            <span className="flex items-center gap-1.5 rounded-lg border border-[#557d61] bg-[#18352a] px-3 py-2 text-xs font-semibold text-[#a9d4ae]">
              <Check className="h-3.5 w-3.5" />{" "}
              {run?.state === "COMPLETED"
                ? "Evidence recorded"
                : (run?.state ?? "Ready")}
            </span>
          )}
        </div>
      </footer>
    </div>
  );
}
