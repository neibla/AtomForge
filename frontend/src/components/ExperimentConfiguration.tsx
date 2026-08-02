import { Cpu, Database, FileJson, ShieldCheck } from "lucide-react";

import type {
  ExperimentBundleResponse,
} from "@/types";
import {
  decisionCalibrationText,
  decisionOutcomeLabel,
  decisionOutcomeTone,
} from "@/lib/scientificDecision";
import { formatValue } from "@/lib/utils";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function dftCalculation(
  bundle: ExperimentBundleResponse,
): Record<string, unknown> | null {
  const results = Object.values(bundle.script_results ?? {}).reverse();
  for (const result of results) {
    if (!isRecord(result) || !isRecord(result.data)) continue;
    const validation = result.data.validation;
    if (!isRecord(validation) || !isRecord(validation.calculation)) continue;
    return validation.calculation;
  }
  return null;
}

function KeyValueGrid({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values).filter(
    ([, value]) => value !== null && value !== "",
  );
  if (!entries.length) {
    return <p className="text-sm text-slate-500">Not recorded</p>;
  }
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {entries.map(([key, value]) => (
        <div key={key} className="min-w-0 border-b border-slate-100 pb-2">
          <dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-400">
            {key.replaceAll("_", " ")}
          </dt>
          <dd className="mt-1 break-words font-mono text-xs text-slate-700 [overflow-wrap:anywhere]">
            {formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function ExperimentConfiguration({
  bundle,
}: {
  bundle: ExperimentBundleResponse;
}) {
  const calculation = dftCalculation(bundle);
  const decision = bundle.scientific_decision;
  const modelEntries = Object.entries(bundle.results.node_model_info);
  const artifactHash = calculation?.source_artifact_sha256;
  const outcomeTone = decision ? decisionOutcomeTone(decision.outcome) : null;
  const outcomeClasses = outcomeTone
    ? {
        success: "border-emerald-200 bg-emerald-50 text-emerald-700",
        warning: "border-amber-200 bg-amber-50 text-amber-700",
        danger: "border-rose-200 bg-rose-50 text-rose-700",
      }[outcomeTone]
    : "";
  const calibrationText = decision ? decisionCalibrationText(decision) : null;

  return (
    <div className="custom-scrollbar h-full overflow-y-auto bg-slate-50 px-6 py-8 lg:px-12 lg:py-10">
      <div className="mx-auto max-w-6xl space-y-5">
        {decision ? (
          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#b96845]">
                  Scientific decision
                </p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950">
                  {decision.headline}
                </h2>
                <p className="mt-2 max-w-4xl text-sm leading-relaxed text-slate-600">
                  {decision.scope}
                </p>
              </div>
              <div className="flex gap-2">
                <span
                  className={`rounded-full border px-3 py-1 font-mono text-xs font-semibold ${outcomeClasses}`}
                >
                  {decisionOutcomeLabel(decision.outcome)}
                </span>
                <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 font-mono text-xs font-semibold text-amber-700">
                  {calibrationText ?? "Calibration not recorded"}
                </span>
              </div>
            </div>
          </section>
        ) : null}

        <div className="grid gap-5 xl:grid-cols-2">
          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Cpu className="h-4 w-4 text-[#b96845]" /> Workflow runtime
            </h3>
            <div className="mt-5">
              <KeyValueGrid
                values={
                  bundle.results.model_info as unknown as Record<
                    string,
                    unknown
                  >
                }
              />
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Database className="h-4 w-4 text-[#b96845]" /> DFT engine and
              protocol
            </h3>
            <div className="mt-5">
              <KeyValueGrid
                values={
                  calculation ?? { status: "No DFT calculation recorded" }
                }
              />
            </div>
          </section>
        </div>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <ShieldCheck className="h-4 w-4 text-[#b96845]" /> Scientific
            modules
          </h3>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {modelEntries.map(([nodeId, model]) => (
              <article
                key={nodeId}
                className="rounded-lg border border-slate-200 bg-slate-50 p-4"
              >
                <p
                  className="truncate font-mono text-xs font-semibold text-slate-800"
                  title={nodeId}
                >
                  {nodeId}
                </p>
                <p className="mt-2 text-sm font-medium text-slate-700">
                  {model.name}
                </p>
                <p className="mt-1 font-mono text-[10px] text-slate-500">
                  {model.version} · {model.device}
                </p>
              </article>
            ))}
            {!modelEntries.length ? (
              <p className="text-sm text-slate-500">
                No module identities recorded.
              </p>
            ) : null}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <FileJson className="h-4 w-4 text-[#b96845]" /> Artifact identity
          </h3>
          <p className="mt-3 break-all font-mono text-xs text-slate-600">
            {typeof artifactHash === "string"
              ? artifactHash
              : "No immutable DFT artifact hash recorded."}
          </p>
        </section>

        <details className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <summary className="cursor-pointer px-6 py-4 text-sm font-semibold text-slate-800">
            View raw experiment record
          </summary>
          <pre className="custom-scrollbar max-h-[38rem] overflow-auto border-t border-slate-200 bg-slate-950 p-5 font-mono text-xs leading-relaxed text-slate-200">
            {JSON.stringify(bundle, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  );
}
