import { describe, expect, test } from "bun:test";

import {
  experimentPaper,
  experimentTitle,
  humanizeIdentifier,
  nodeTitle,
} from "./experimentPresentation";

describe("experiment presentation", () => {
  test("uses readable names for the retained Berger runs", () => {
    expect(experimentTitle("berger-vacancy-reproduction-20260801-r2")).toBe(
      "Berger vacancy reproduction",
    );
    expect(
      experimentTitle("berger-vacancy-gpaw-validation-20260801-r2"),
    ).toBe("Berger vacancy reproduction — held-out DFT validation");
  });

  test("humanizes arbitrary identifiers without losing acronyms", () => {
    expect(humanizeIdentifier("study-20260730-bcc-w-eos")).toBe(
      "Study BCC W EOS",
    );
    expect(nodeTitle("select_dft_case")).toBe("Select DFT candidate");
  });

  test("extracts the recorded arXiv source from script evidence", () => {
    const bundle = {
      spec: {
        experiment_id: "berger-vacancy-reproduction-20260801-r2",
      },
      script_results: {
        prepare_paper_subset: {
          data: {
            source: {
              title: "Paper title",
              arxiv: "https://arxiv.org/abs/2504.06993",
            },
          },
        },
      },
    } as never;

    expect(experimentPaper(bundle)).toEqual({
      title: "Paper title",
      url: "https://arxiv.org/abs/2504.06993",
    });
  });

  test("normalizes paper identifiers and arXiv URLs from older evidence", () => {
    const bundle = {
      spec: { experiment_id: "eqvol-silicon-demo-20260730" },
      script_results: {
        fit_eos: {
          data: {
            source: {
              title: "Silicon equation of state",
              arxiv: "1903.10216v1",
            },
          },
        },
      },
    } as never;

    expect(experimentPaper(bundle)).toEqual({
      title: "Silicon equation of state",
      url: "https://arxiv.org/abs/1903.10216v1",
    });
  });

  test("accepts arxiv_id and url source fields", () => {
    const bundle = {
      spec: { experiment_id: "smoothness-study-20260801" },
      script_results: {
        analyze: {
          data: {
            source: {
              arxiv_id: "2602.04861v2",
              url: "https://arxiv.org/abs/2602.04861",
            },
          },
        },
      },
    } as never;

    expect(experimentPaper(bundle)).toEqual({
      title: "arXiv: 2602.04861v2",
      url: "https://arxiv.org/abs/2602.04861",
    });
  });
});
