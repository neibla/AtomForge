import type { ExperimentBundleResponse } from "@/types";

export interface PaperReference {
  title: string;
  url: string;
}

const BERGER_PAPER: PaperReference = {
  title:
    "Screening of material defects using universal machine-learning interatomic potentials",
  url: "https://arxiv.org/abs/2504.06993",
};

const WORD_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  bcc: "BCC",
  bsct: "BSCT",
  dft: "DFT",
  eos: "EOS",
  gpaw: "GPAW",
  mace: "MACE",
  mattersim: "MatterSim",
  mp: "MP",
  nvt: "NVT",
  pka: "PKA",
  r2: "R2",
  sim: "Simulation",
  sweep: "Sweep",
};

const NODE_LABELS: Record<string, string> = {
  evaluate_mattersim: "Evaluate with MatterSim",
  prepare_paper_subset: "Prepare paper subset",
  reproduce_mace: "Reproduce with MACE",
  run_independent_dft: "Run independent DFT",
  select_dft_case: "Select DFT candidate",
  validate_promoted_candidate_with_dft: "Validate candidate with DFT",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function humanizeIdentifier(value: string): string {
  const words = value
    .replace(/\b\d{8,}\b/g, " ")
    .replace(/\br\d+\b/gi, " ")
    .replace(/[-_]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  return words
    .map((word) => {
      const normalized = word.toLowerCase();
      return WORD_LABELS[normalized] ?? (word.length === 1 ? word.toUpperCase() : word);
    })
    .join(" ")
    .replace(/^\w/, (first) => first.toUpperCase());
}

export function experimentTitle(experimentId: string): string {
  const normalized = experimentId.toLowerCase();
  if (normalized.includes("berger-vacancy-gpaw-validation")) {
    return "Berger vacancy reproduction — held-out DFT validation";
  }
  if (normalized.includes("berger-vacancy-reproduction")) {
    return "Berger vacancy reproduction";
  }
  return humanizeIdentifier(experimentId);
}

export function nodeTitle(nodeId: string): string {
  return NODE_LABELS[nodeId] ?? humanizeIdentifier(nodeId);
}

function findPaperReference(value: unknown): PaperReference | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const reference = findPaperReference(item);
      if (reference) return reference;
    }
    return null;
  }
  if (!isRecord(value)) return null;

  const arxivValue =
    typeof value.arxiv === "string"
      ? value.arxiv
      : typeof value.arxiv_id === "string"
        ? value.arxiv_id
        : null;
  const explicitUrl = typeof value.url === "string" ? value.url : null;
  const arxivId = arxivValue?.match(/^(\d{4}\.\d{4,5})(v\d+)?$/i);
  const url =
    explicitUrl && /^https:\/\/arxiv\.org\/abs\/[\w.-]+$/.test(explicitUrl)
      ? explicitUrl
      : arxivValue && /^https:\/\/arxiv\.org\/abs\/[\w.-]+$/.test(arxivValue)
        ? arxivValue
        : arxivId
          ? `https://arxiv.org/abs/${arxivValue}`
          : null;
  if (url) {
    return {
      title:
        typeof value.title === "string"
          ? value.title
          : arxivValue
            ? `arXiv: ${arxivValue}`
            : BERGER_PAPER.title,
      url,
    };
  }

  for (const item of Object.values(value)) {
    const reference = findPaperReference(item);
    if (reference) return reference;
  }
  return null;
}

export function experimentPaper(
  bundle: ExperimentBundleResponse,
): PaperReference | null {
  const recorded = findPaperReference(bundle.script_results);
  if (recorded) return recorded;
  return bundle.spec.experiment_id.toLowerCase().includes("berger-vacancy")
    ? BERGER_PAPER
    : null;
}
