import { useState } from "react";
import { ChevronDown, GitBranch, ShieldCheck, Trash2, X } from "lucide-react";

import { cn, formatValue } from "@/lib/utils";
import { nodeTitle } from "@/lib/experimentPresentation";
import {
  formatSweepRange,
  formatSweepStep,
  sweepPresentation,
} from "@/lib/sweeps";
import type {
  DagNode,
  ExperimentBundleResponse,
  ExperimentSpec,
  RunRecordResponse,
  SweepResult,
} from "@/types";

import {
  defaultNodeParams,
  dependencyIds,
  metricsForNode,
  NODE_META,
  nodeStatus,
  paramsForEditor,
  statusClass,
  statusLabel,
} from "./experimentGraphModel";

export function ExperimentNodeInspector({
  bundle,
  run,
  node,
  sweepResult,
  sweepLoading,
  sweepError,
}: {
  bundle: ExperimentBundleResponse;
  run: RunRecordResponse | null;
  node: DagNode;
  sweepResult: SweepResult | null;
  sweepLoading: boolean;
  sweepError: string | null;
}) {
  const meta = NODE_META[node.type];
  const sweep = sweepPresentation(node);
  const params = node.params ?? {};
  const status = nodeStatus(run, node, bundle);
  const metrics = metricsForNode(bundle, node.id);
  const hypotheses = bundle.results.hypotheses.filter(
    (hypothesis) =>
      hypothesis.target_node === node.id ||
      (!hypothesis.target_node &&
        (bundle.spec.hypotheses ?? []).some(
          (declared) => declared.id === hypothesis.id && declared.target_node === node.id,
        )),
  );

  return (
    <aside className="custom-scrollbar min-w-0 min-h-0 overflow-x-hidden overflow-y-auto border-t border-[#30464f] bg-[#15232a] px-5 py-5 lg:border-l lg:border-t-0 lg:px-6 lg:py-7">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#d5794f]">
            Node inspector
          </p>
          <h3 className="mt-2 text-lg font-semibold text-[#f2f7f4]">
            {nodeTitle(node.id)}
          </h3>
          <p className="mt-1 font-mono text-[9px] text-[#70868f]">{node.id}</p>
          <p className="mt-1 text-xs text-[#91a5ad]">
            {meta.label} · {node.type}
          </p>
        </div>
        <span
          className={cn(
            "rounded-full border px-2 py-1 text-[9px] font-semibold uppercase tracking-[0.08em]",
            statusClass(status),
          )}
        >
          {statusLabel(status)}
        </span>
      </div>

      <div className="mt-5 border-y border-[#30464f] py-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#d5794f]">
          Node purpose
        </p>
        <p className="mt-2 text-xs leading-relaxed text-[#c2cfcd]">
          {meta.description}
        </p>
      </div>

      {node.type === "SCRIPT" ? (
        <section className="mt-5 min-w-0 rounded-lg border border-[#5b4a52] bg-[#1d2930] p-3">
          <div>
            <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#f0b36e]">
              Project script contract
            </h4>
          </div>
          <dl className="mt-3 min-w-0 space-y-2 text-[10px]">
            <div className="flex min-w-0 items-start justify-between gap-3">
              <dt className="shrink-0 text-[#91a5ad]">Source</dt>
              <dd
                className="min-w-0 max-w-[12rem] truncate text-right font-mono text-[#edf1eb]"
                title={String(params.script ?? "not set")}
              >
                {String(params.script ?? "not set")}
              </dd>
            </div>
            <div className="flex min-w-0 items-center justify-between gap-3">
              <dt className="shrink-0 text-[#91a5ad]">Profile</dt>
              <dd className="min-w-0 truncate font-mono text-[#d8a867]">
                {String(params.execution_profile ?? "analysis")}
              </dd>
            </div>
            <div className="flex min-w-0 items-center justify-between gap-3">
              <dt className="shrink-0 text-[#91a5ad]">Arguments</dt>
              <dd className="min-w-0 truncate font-mono text-[#d9e6df]">
                {params.arguments && typeof params.arguments === "object"
                  ? `${Object.keys(params.arguments as Record<string, unknown>).length} keys`
                  : "none"}
              </dd>
            </div>
            <div className="flex min-w-0 items-start justify-between gap-3">
              <dt className="shrink-0 text-[#91a5ad]">Outputs</dt>
              <dd className="min-w-0 max-w-[12rem] break-words text-right font-mono text-[#d9e6df] [overflow-wrap:anywhere]">
                {params.output_metrics &&
                typeof params.output_metrics === "object"
                  ? Object.keys(
                      params.output_metrics as Record<string, unknown>,
                    ).join(", ")
                  : "not declared"}
              </dd>
            </div>
          </dl>
          <p className="mt-3 border-t border-[#30464f] pt-2 text-[10px] leading-relaxed text-[#a7b4b3]">
            The source lives in this local project; this panel records the
            script contract used by the run.
          </p>
        </section>
      ) : null}

      {sweep ? (
        <section className="mt-5 rounded-lg border border-[#3b586c] bg-[#152a35] p-3">
          <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91b9da]">
            Sweep parameter
          </h4>
          <div className="mt-2 rounded-md border border-[#3b586c] bg-[#10232d] px-3 py-2">
            <p className="text-sm font-semibold text-[#edf3f4]">{sweep.label}</p>
            <p className="mt-1 font-mono text-xs text-[#b9d0dd]">
              {formatSweepRange(sweep)}
            </p>
            <p className="mt-1 text-[10px] text-[#91a5ad]">
              {sweep.sampleCount} samples · {formatSweepStep(sweep)}
            </p>
          </div>
          <dl className="mt-3 space-y-2 border-t border-[#30464f] pt-3 text-[10px]">
            <div className="flex justify-between gap-3">
              <dt className="text-[#91a5ad]">Operation</dt>
              <dd className="text-right text-[#e0e9e6]">{sweep.operationLabel}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[#91a5ad]">Applies to</dt>
              <dd className="text-right text-[#e0e9e6]">{sweep.targetLabel}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[#91a5ad]">Transform</dt>
              <dd className="text-right text-[#e0e9e6]">{sweep.transformLabel}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-[#91a5ad]">Concurrency</dt>
              <dd className="font-mono text-[#e0e9e6]">
                {sweep.maxConcurrency}
              </dd>
            </div>
          </dl>
        </section>
      ) : null}

      {node.type === "SWEEP" && sweepLoading ? (
        <p className="mt-3 text-[10px] text-[#91a5ad]">
          Loading recorded sweep points…
        </p>
      ) : null}
      {node.type === "SWEEP" && sweepError ? (
        <p className="mt-3 rounded-lg border border-[#78484d] bg-[#3a252a] p-3 text-[10px] leading-relaxed text-[#f1a7a1]">
          Recorded sweep evidence could not be verified: {sweepError}
        </p>
      ) : null}
      {node.type === "SWEEP" && sweepResult
        ? (() => {
            const completed = sweepResult.points.filter(
              (point) => point.status === "COMPLETED",
            );
            const failed = sweepResult.points.filter(
              (point) => point.status === "FAILED",
            );
            const trialCount = completed.reduce(
              (count, point) => count + (point.ensemble?.length ?? 0),
              0,
            );
            return (
              <section className="mt-3 rounded-lg border border-[#3b586c] bg-[#101f27] p-3">
                <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91b9da]">
                  Recorded sweep evidence
                </h4>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-[10px]">
                  <div className="rounded border border-[#30464f] p-2">
                    <dt className="text-[#91a5ad]">Completed</dt>
                    <dd className="mt-1 font-mono text-[#a9d4ae]">
                      {completed.length}
                    </dd>
                  </div>
                  <div className="rounded border border-[#30464f] p-2">
                    <dt className="text-[#91a5ad]">Failed</dt>
                    <dd className="mt-1 font-mono text-[#f1a7a1]">
                      {failed.length}
                    </dd>
                  </div>
                  <div className="rounded border border-[#30464f] p-2">
                    <dt className="text-[#91a5ad]">Trials</dt>
                    <dd className="mt-1 font-mono text-[#e0e9e6]">
                      {trialCount}
                    </dd>
                  </div>
                </dl>
                {failed.length ? (
                  <div className="mt-3 border-t border-[#30464f] pt-3">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#e18d87]">
                      Failed points
                    </p>
                    <ul className="mt-2 space-y-2">
                      {failed.slice(0, 6).map((point) => (
                        <li
                          key={point.id}
                          className="min-w-0 text-[10px] leading-relaxed text-[#d9b2ae]"
                        >
                          <span className="font-mono text-[#f1a7a1]">
                            {formatValue(point.value)}{" "}
                            {sweepResult.coordinate.unit}
                          </span>
                          <span className="ml-2 break-words [overflow-wrap:anywhere]">
                            {point.error}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </section>
            );
          })()
        : null}

      <div className="mt-6 border-y border-[#30464f] py-4">
        <div className="flex items-center gap-2 text-xs font-semibold text-[#e6efeb]">
          <GitBranch className="h-3.5 w-3.5 text-[#d5794f]" /> Dependencies
        </div>
        <p className="mt-2 break-words font-mono text-[11px] text-[#91a5ad] [overflow-wrap:anywhere]">
          {dependencyIds(node).map(nodeTitle).join(", ") || "Entry node"}
        </p>
      </div>

      <div className="mt-5">
        <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
          Parameters
        </h4>
        <div className="mt-2 overflow-hidden rounded-lg border border-[#30464f]">
          {Object.entries(node.params ?? {})
            .slice(0, 8)
            .map(([key, value]) => (
              <div
                key={key}
                className="grid grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] gap-3 border-b border-[#30464f] px-3 py-2 last:border-b-0"
              >
                <span className="truncate text-[10px] text-[#91a5ad]">
                  {key}
                </span>
                <span className="truncate text-right font-mono text-[10px] text-[#e0e9e6]">
                  {formatValue(value)}
                </span>
              </div>
            ))}
        </div>
      </div>

      {metrics.length ? (
        <div className="mt-5">
          <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Recorded metrics
          </h4>
          <div className="mt-2 overflow-hidden rounded-lg border border-[#30464f]">
            {metrics.map(([name, value]) => (
              <div
                key={name}
                className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 border-b border-[#30464f] px-3 py-2 last:border-b-0"
              >
                <span className="truncate text-[10px] text-[#91a5ad]">
                  {name}
                </span>
                <span className="font-mono text-[10px] text-[#d9e6df]">
                  {value}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mt-5 border-t border-[#30464f] pt-4">
        <h4 className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
          <ShieldCheck className="h-3.5 w-3.5 text-[#79c28a]" /> Provenance
        </h4>
        <div className="mt-2 space-y-2 text-[10px] text-[#a7b4b3]">
          <p className="min-w-0">
            Experiment{" "}
            <span className="float-right max-w-[12rem] break-words text-right font-mono text-[#e0e9e6] [overflow-wrap:anywhere]">
              {bundle.spec.experiment_id}
            </span>
          </p>
          <p className="min-w-0">
            Parent{" "}
            <span className="float-right max-w-[12rem] break-words text-right font-mono text-[#e0e9e6] [overflow-wrap:anywhere]">
              {bundle.spec.parent_experiment_id ?? "—"}
            </span>
          </p>
        </div>
      </div>

      {hypotheses.length ? (
        <div className="mt-5 border-t border-[#30464f] pt-4">
          <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Checks
          </h4>
          {hypotheses.map((hypothesis) => (
            <div
              key={hypothesis.id}
              className="mt-2 rounded border border-[#30464f] px-2 py-2 text-[10px]"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-[#a7b4b3]">{hypothesis.id}</span>
                <span
                  className={cn(
                    "font-semibold",
                    hypothesis.status === "PASSED"
                      ? "text-[#86b88e]"
                      : hypothesis.status === "FAILED"
                        ? "text-[#e18d87]"
                        : "text-[#d8a867]",
                  )}
                >
                  {hypothesis.status}
                </span>
              </div>
              <p className="mt-1 font-mono text-[#d9e6df]">
                {hypothesis.metric}: {hypothesis.value}
              </p>
              {hypothesis.status === "REVIEW" && hypothesis.review_reason ? (
                <p className="mt-1 leading-relaxed text-[#d8a867]">
                  {hypothesis.review_reason.replaceAll("_", " ")}
                  {hypothesis.detail ? ` — ${hypothesis.detail}` : ""}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </aside>
  );
}

function parseParams(value: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function ExperimentNodeEditor({
  draft,
  selectedId,
  onChange,
  onValidityChange,
  onSelectedIdChange,
  onDelete,
  onClose,
}: {
  draft: ExperimentSpec;
  selectedId: string;
  onChange: (spec: ExperimentSpec) => void;
  onValidityChange: (error: string | null) => void;
  onSelectedIdChange: (id: string) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const node =
    draft.dag.find((candidate) => candidate.id === selectedId) ?? draft.dag[0];
  const [paramsText, setParamsText] = useState(() =>
    node ? paramsForEditor(node) : "{}",
  );
  const [paramsError, setParamsError] = useState<string | null>(null);
  const [scriptArgumentsText, setScriptArgumentsText] = useState(() =>
    JSON.stringify((node?.params ?? {}).arguments ?? {}, null, 2),
  );
  const [scriptOutputsText, setScriptOutputsText] = useState(() =>
    JSON.stringify((node?.params ?? {}).output_metrics ?? {}, null, 2),
  );
  if (!node) return null;
  const meta = NODE_META[node.type];
  const params = node.params ?? {};

  function updateNode(changes: Partial<DagNode>) {
    const nextId = changes.id ?? node.id;
    const renamed = nextId !== node.id;
    const nextNode = { ...node, ...changes, id: nextId };
    setParamsText(paramsForEditor(nextNode));
    setScriptArgumentsText(
      JSON.stringify((nextNode.params ?? {}).arguments ?? {}, null, 2),
    );
    setScriptOutputsText(
      JSON.stringify((nextNode.params ?? {}).output_metrics ?? {}, null, 2),
    );
    setParamsError(null);
    onValidityChange(null);
    onChange({
      ...draft,
      decision_node_id:
        renamed && draft.decision_node_id === node.id
          ? nextId
          : draft.decision_node_id,
      dag: draft.dag.map((candidate) => {
        const candidateId = candidate.id === node.id ? nextId : candidate.id;
        const dependencies = dependencyIds(candidate).map((dependency) =>
          dependency === node.id ? nextId : dependency,
        );
        return candidate.id === node.id
          ? { ...candidate, ...changes, id: candidateId }
          : renamed
            ? {
                ...candidate,
                depends_on: dependencies.length ? dependencies : null,
              }
            : candidate;
      }),
    });
    if (renamed) onSelectedIdChange(nextId);
  }

  function updateParamText(value: string) {
    setParamsText(value);
    const parsed = parseParams(value);
    if (!parsed) {
      const error = "Parameters must be a JSON object.";
      setParamsError(error);
      onValidityChange(error);
      return;
    }
    setParamsError(null);
    updateNode({ params: parsed });
  }

  function toggleDependency(dependency: string) {
    const current = new Set(dependencyIds(node));
    if (current.has(dependency)) current.delete(dependency);
    else current.add(dependency);
    updateNode({ depends_on: current.size ? Array.from(current) : null });
  }

  function updateScriptObjectParam(
    key: "arguments" | "output_metrics",
    value: string,
    setText: (next: string) => void,
  ) {
    setText(value);
    const parsed = parseParams(value);
    if (!parsed) {
      const error = `${key} must be a JSON object.`;
      setParamsError(error);
      onValidityChange(error);
      return;
    }
    setParamsError(null);
    updateNode({ params: { ...params, [key]: parsed } });
  }

  return (
    <aside className="custom-scrollbar min-w-0 min-h-0 overflow-x-hidden overflow-y-auto border-t border-[#30464f] bg-[#15232a] px-5 py-5 lg:border-l lg:border-t-0 lg:px-6 lg:py-7">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#d5794f]">
            Draft inspector
          </p>
          <h3 className="mt-2 text-lg font-semibold text-[#f2f7f4]">
            Edit node
          </h3>
        </div>
        <button
          type="button"
          aria-label="Close draft inspector"
          onClick={onClose}
          className="rounded-lg p-1.5 text-[#91a5ad] hover:bg-[#203842] hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <label className="mt-6 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
        Node id
        <input
          value={node.id}
          onChange={(event) =>
            updateNode({
              id: event.target.value.replace(/[^a-zA-Z0-9_-]/g, "_"),
            })
          }
          className="mt-2 w-full rounded-lg border border-[#466372] bg-[#0f1c23] px-3 py-2 font-mono text-xs text-[#edf1eb] outline-none focus:border-[#d5794f]"
        />
      </label>

      <label className="mt-4 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
        Node type
        <span className="relative mt-2 block">
          <select
            value={node.type}
            onChange={(event) => {
              const type = event.target.value as DagNode["type"];
              updateNode({ type, params: defaultNodeParams(type) });
            }}
            className="w-full appearance-none rounded-lg border border-[#466372] bg-[#0f1c23] px-3 py-2 text-xs text-[#edf1eb] outline-none focus:border-[#d5794f]"
          >
            {Object.keys(NODE_META).map((type) => (
              <option key={type} value={type}>
                {type} · {NODE_META[type as DagNode["type"]].label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-2.5 h-3.5 w-3.5 text-[#91a5ad]" />
        </span>
      </label>

      <fieldset className="mt-5">
        <legend className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
          Upstream dependencies
        </legend>
        <p className="mt-2 text-[10px] leading-relaxed text-[#91a5ad]">
          Select nodes that must finish before this node. The graph will draw
          arrows for the saved chain. {meta.dependencyHint}
        </p>
        <div className="mt-2 space-y-2 rounded-lg border border-[#30464f] p-3">
          {draft.dag
            .filter((candidate) => candidate.id !== node.id)
            .map((candidate) => (
              <label
                key={candidate.id}
                className="flex items-center gap-2 text-xs text-[#d9e6df]"
              >
                <input
                  aria-label={`Make ${candidate.id} an upstream dependency`}
                  type="checkbox"
                  checked={dependencyIds(node).includes(candidate.id)}
                  onChange={() => toggleDependency(candidate.id)}
                  className="accent-[#d5794f]"
                />
                <span className="font-mono">{candidate.id}</span>
                <span className="text-[10px] text-[#91a5ad]">
                  · {candidate.type}
                </span>
              </label>
            ))}
          {draft.dag.length === 1 ? (
            <p className="text-[11px] text-[#91a5ad]">
              Entry node has no dependencies.
            </p>
          ) : null}
        </div>
      </fieldset>

      {node.type === "SCRIPT" ? (
        <section className="mt-5 rounded-lg border border-[#5b4a52] bg-[#1d2930] p-3">
          <h4 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#f0b36e]">
            SCRIPT contract
          </h4>
          <p className="mt-2 text-[10px] leading-relaxed text-[#a7b4b3]">
            For this local POC, scripts are project `.py` files under
            `atomforge/node_scripts`. The validator checks the profile and
            declared outputs before queueing.
          </p>
          <label className="mt-4 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Project script file
            <input
              value={String(params.script ?? "")}
              onChange={(event) =>
                updateNode({
                  params: { ...params, script: event.target.value },
                })
              }
              placeholder="example.py"
              className="mt-2 w-full rounded-lg border border-[#466372] bg-[#0f1c23] px-3 py-2 font-mono text-[11px] text-[#edf1eb] outline-none focus:border-[#d5794f]"
            />
          </label>
          <label className="mt-4 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Execution profile
            <select
              value={String(params.execution_profile ?? "analysis")}
              onChange={(event) =>
                updateNode({
                  params: { ...params, execution_profile: event.target.value },
                })
              }
              className="mt-2 w-full rounded-lg border border-[#466372] bg-[#0f1c23] px-3 py-2 text-[11px] text-[#edf1eb] outline-none focus:border-[#d5794f]"
            >
              <option value="analysis">analysis · local/script analysis</option>
              <option value="physics_gpu">
                physics_gpu · provenance-gated GPU
              </option>
            </select>
          </label>
          <label className="mt-4 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Output metrics JSON
            <textarea
              value={scriptOutputsText}
              onChange={(event) =>
                updateScriptObjectParam(
                  "output_metrics",
                  event.target.value,
                  setScriptOutputsText,
                )
              }
              spellCheck={false}
              className="custom-scrollbar mt-2 h-28 w-full resize-y rounded-lg border border-[#466372] bg-[#0f1c23] p-3 font-mono text-[11px] leading-relaxed text-[#edf1eb] outline-none focus:border-[#d5794f]"
            />
          </label>
          <label className="mt-4 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
            Script arguments JSON
            <textarea
              value={scriptArgumentsText}
              onChange={(event) =>
                updateScriptObjectParam(
                  "arguments",
                  event.target.value,
                  setScriptArgumentsText,
                )
              }
              spellCheck={false}
              className="custom-scrollbar mt-2 h-28 w-full resize-y rounded-lg border border-[#466372] bg-[#0f1c23] p-3 font-mono text-[11px] leading-relaxed text-[#edf1eb] outline-none focus:border-[#d5794f]"
            />
          </label>
        </section>
      ) : null}

      <label className="mt-5 block text-[10px] font-semibold uppercase tracking-[0.12em] text-[#91a5ad]">
        Parameters JSON
        <textarea
          value={paramsText}
          onChange={(event) => updateParamText(event.target.value)}
          spellCheck={false}
          className="custom-scrollbar mt-2 h-48 w-full resize-y rounded-lg border border-[#466372] bg-[#0f1c23] p-3 font-mono text-[11px] leading-relaxed text-[#edf1eb] outline-none focus:border-[#d5794f]"
        />
      </label>
      {paramsError ? (
        <p className="mt-2 text-[11px] text-[#e18d87]">{paramsError}</p>
      ) : (
        <p className="mt-2 text-[10px] leading-relaxed text-[#91a5ad]">
          The graph topology is constrained. Parameter JSON is validated before
          queueing and preserves advanced node-specific arguments.
        </p>
      )}

      <button
        type="button"
        onClick={onDelete}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg border border-[#78484d] px-3 py-2 text-xs font-semibold text-[#e18d87] hover:bg-[#3a252a]"
      >
        <Trash2 className="h-3.5 w-3.5" /> Remove node
      </button>
    </aside>
  );
}
