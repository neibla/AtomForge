import {
  CheckCircle2,
  CircleAlert,
  CircleDashed,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  ShieldCheck,
} from "lucide-react";

import { cn } from "@/lib/utils";
import {
  experimentPaper,
  humanizeIdentifier,
  nodeTitle,
} from "@/lib/experimentPresentation";
import {
  decisionCalibrationText,
  decisionOutcomeLabel,
  decisionOutcomeTone,
} from "@/lib/scientificDecision";
import type { Hypothesis } from "@/api/model/hypothesis";
import type {
  ExperimentBundleResponse,
  HypothesisEval,
  ScientificDecision,
} from "@/types";

const OUTCOME_BADGES = {
  success: "border-[#557d61] bg-[#18352a] text-[#a9d4ae]",
  warning: "border-[#846844] bg-[#3a3022] text-[#e7bd7e]",
  danger: "border-[#78484d] bg-[#3a252a] text-[#f1a7a1]",
} as const;

const OUTCOME_ICONS = {
  success: CheckCircle2,
  warning: CircleDashed,
  danger: CircleAlert,
} as const;

function hypothesisText(hypothesis: Hypothesis): string {
  if (hypothesis.assertion) {
    const assertion = hypothesis.assertion.replaceAll("target.", "");
    return `Tests whether ${nodeTitle(hypothesis.target_node)} meets ${assertion}.`;
  }
  if (hypothesis.metric)
    return `Measures ${humanizeIdentifier(hypothesis.metric)} on ${nodeTitle(hypothesis.target_node)}.`;
  return `Evaluates ${nodeTitle(hypothesis.target_node)}.`;
}

function evaluationTone(evaluation: HypothesisEval | undefined): string {
  if (evaluation?.status === "PASSED") return "text-[#86b88e]";
  if (evaluation?.status === "FAILED") return "text-[#e18d87]";
  return "text-[#d8a867]";
}

function EvidenceDetails({
  decision,
  evaluations,
}: {
  decision: ScientificDecision;
  evaluations: HypothesisEval[];
}) {
  const checks = decision.quality_checks ?? [];
  const claims = decision.supported_claims ?? [];
  const limitations = decision.limitations ?? [];

  return (
    <details className="group mt-4 border-t border-[#30464f] pt-3">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#a7b4b3] hover:text-[#f0f5f1]">
        <span className="flex items-center gap-2">
          <ShieldCheck className="h-3.5 w-3.5 text-[#79c28a]" /> Evidence,
          checks &amp; limits
        </span>
        <span className="font-mono text-[#d5794f] group-open:hidden">+</span>
        <span className="hidden font-mono text-[#d5794f] group-open:inline">
          −
        </span>
      </summary>
      <div className="mt-3 grid gap-4 lg:grid-cols-3">
        <SummaryList
          title="What this establishes"
          items={claims}
          empty="No supported claims recorded."
        />
        <SummaryList
          title="Explicit limits"
          items={limitations}
          empty="No limitations recorded."
        />
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#78919a]">
            Acceptance checks
          </p>
          {evaluations.length || checks.length ? (
            <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-[#c0cecc]">
              {evaluations.map((evaluation) => (
                <li
                  key={evaluation.id}
                  className="flex items-start justify-between gap-3"
                >
                  <span className="min-w-0 truncate" title={evaluation.id}>
                    {evaluation.id}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 font-semibold",
                      evaluationTone(evaluation),
                    )}
                  >
                    {evaluation.status}
                  </span>
                </li>
              ))}
              {!evaluations.length
                ? checks.map((check) => (
                    <li
                      key={check.label}
                      className="flex items-start justify-between gap-3"
                    >
                      <span className="min-w-0 truncate" title={check.label}>
                        {check.label}
                      </span>
                      <span className="shrink-0 font-mono text-[#d8a867]">
                        {check.value} {check.unit}
                      </span>
                    </li>
                  ))
                : null}
            </ul>
          ) : (
            <p className="mt-2 text-[11px] text-[#91a5ad]">
              No checks recorded.
            </p>
          )}
        </div>
      </div>
    </details>
  );
}

function SummaryList({
  title,
  items,
  empty,
}: {
  title: string;
  items: string[];
  empty: string;
}) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#78919a]">
        {title}
      </p>
      {items.length ? (
        <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-[#c0cecc]">
          {items.slice(0, 4).map((item) => (
            <li key={item}>— {item}</li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[11px] text-[#91a5ad]">{empty}</p>
      )}
    </div>
  );
}

export function ExperimentSummary({
  bundle,
}: {
  bundle: ExperimentBundleResponse;
}) {
  const hypotheses = bundle.spec.hypotheses ?? [];
  const evaluations = bundle.results.hypotheses ?? [];
  const decision = bundle.scientific_decision;
  const outcomeTone = decisionOutcomeTone(decision.outcome);
  const OutcomeIcon = OUTCOME_ICONS[outcomeTone];
  const paper = experimentPaper(bundle);
  const passed = evaluations.filter(
    (evaluation) => evaluation.status === "PASSED",
  ).length;
  const calibrationText = decisionCalibrationText(decision);

  return (
    <section
      aria-labelledby="experiment-summary-title"
      className="brief-summary shrink-0 border-b border-[#30464f] bg-[#15232a] px-5 py-2.5 lg:px-8"
    >
      <details className="brief-details">
        <summary className="flex cursor-pointer list-none items-center gap-3 rounded-md py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-[#d5794f]/60">
          <span className="flex shrink-0 items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-[#d5794f]">
            <FlaskConical className="h-3.5 w-3.5" /> Run brief
          </span>
          <span className="min-w-0 flex-1 truncate text-xs font-medium text-[#dce7e4]">
            {decision.headline}
          </span>
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#79c28a]">
              Overall result
            </span>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]",
                OUTCOME_BADGES[outcomeTone],
              )}
            >
              <OutcomeIcon className="h-3 w-3" />{" "}
              {decisionOutcomeLabel(decision.outcome)}
            </span>
            {evaluations.length ? (
              <span className="font-mono text-[10px] text-[#91a5ad]">
                {passed}/{evaluations.length} checks passed
              </span>
            ) : null}
            {calibrationText ? (
              <span className="font-mono text-[10px] text-[#91a5ad]">
                {calibrationText}
              </span>
            ) : null}
          </span>
          <span className="hidden shrink-0 items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-[#91a5ad] sm:flex">
            Details
            <ChevronDown className="brief-details-chevron h-3.5 w-3.5 transition-transform" />
          </span>
        </summary>

        <div className="mt-3 grid gap-5 border-t border-[#30464f] pt-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(18rem,0.75fr)]">
          <div className="min-w-0">
            <h2
              id="experiment-summary-title"
              className="text-sm font-semibold text-[#f2f7f4]"
            >
              What this run is testing
            </h2>
            {hypotheses.length ? (
              <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-[#c8d5d2]">
                {hypotheses.slice(0, 2).map((hypothesis) => (
                  <li
                    key={hypothesis.id}
                    className="flex min-w-0 items-start gap-2"
                  >
                    <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[#d5794f]" />
                    <span className="min-w-0">
                      <span className="font-semibold text-[#edf1eb]">
                        {humanizeIdentifier(hypothesis.id)}
                      </span>
                      <span className="mx-1.5 text-[#718993]">·</span>
                      <span className="font-mono text-[11px] text-[#b9c9c8]">
                        {hypothesisText(hypothesis)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs leading-relaxed text-[#a7b4b3]">
                No predeclared hypothesis was recorded. Use the workflow and
                report to infer the experiment’s scope.
              </p>
            )}
            {hypotheses.length > 2 ? (
              <p className="mt-2 text-[10px] text-[#78919a]">
                + {hypotheses.length - 2} more declared checks
              </p>
            ) : null}
            {paper ? (
              <div className="mt-4 rounded-lg border border-[#35515e] bg-[#101f27] px-3 py-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#d8a867]">
                  Research basis
                </p>
                <a
                  href={paper.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1.5 flex items-start gap-1.5 text-xs font-semibold leading-relaxed text-[#f0c1a8] underline decoration-[#9a604b] underline-offset-2 hover:text-[#ffd5bd]"
                >
                  <span>{paper.title}</span>
                  <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                </a>
                <p className="mt-1 text-[10px] leading-relaxed text-[#91a5ad]">
                  arXiv paper used for the frozen reference dataset and
                  reproduction protocol.
                </p>
              </div>
            ) : null}
          </div>
          <div className="min-w-0 rounded-lg border border-[#263f49] bg-[#101f27] px-3 py-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[#78919a]">
              Run scope
            </p>
            <p className="mt-2 text-sm font-semibold leading-snug text-[#f2f7f4]">
              {decision.headline}
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-[#a7b4b3]">
              {decision.scope}
            </p>
          </div>
        </div>
        <EvidenceDetails decision={decision} evaluations={evaluations} />
      </details>
    </section>
  );
}
