# BSCT-inspired tungsten smoothness study — 2026-08-01

## Objective

Discover a recent, scientifically interesting materials-science result whose smaller claim can be
tested honestly with AtomForge. The selection criterion is not novelty alone: the paper must expose
a quantitative observable compatible with the checked-out engine, such as relaxed energy/force,
finite-temperature structural statistics, or radiation-defect counts.

Primary source paper: **Liu et al., arXiv:2602.04861v2**,
<https://arxiv.org/abs/2602.04861>.

Additional shortlisted sources:

- **Pitigoi and Hatton, arXiv:2607.18472v1**,
  <https://arxiv.org/abs/2607.18472>.
- **Wang, Mosquera-Lois, and Walsh, arXiv:2603.05238v2**,
  <https://arxiv.org/abs/2603.05238>.

## Pre-Flight

- Primary search path: the committed `arxiv-researcher` helper.
- Candidate scope searched: defects, radiation-tolerant refractory alloys, finite-temperature phase
  stability, and universal-MLIP failure modes.
- Selected direction: a **BSCT-inspired inorganic bond/displacement smoothness probe**, because the
  paper's central warning—ordinary energy/force accuracy can miss non-smooth potential-energy
  surfaces—can be reduced to observables AtomForge already exposes.
- Intended DAG shape: `FETCH -> ALLOY(supercell) -> parallel SIMULATE(single_point displacement
  scan) -> trusted SCRIPT(curve diagnostics)`, followed by a bounded stability check only if the
  scan finds an anomaly.
- Intended execution path if a candidate is selected for a run:
  `uv run modal run atomforge/platform/modal/deployment.py --spec-path experiments/dags/<study>.json`.
- Current phase: **execution complete**. The user authorized the recommended BSCT-inspired run on
  2026-08-01; the ordinary Modal DAG completed successfully and its persisted bundle was checked
  independently before interpretation.

## Scientific Interpretation Contract

- `method_alignment`: **cross_method**. The paper's BSCT benchmark uses molecular fragment bond
  scans and DFT force references; the proposed AtomForge study would use inorganic structures and
  the available foundation MLIP checkpoint(s).
- `threshold_rationale`: the first pass should be descriptive. A force-curve smoothness score or
  anomaly flag must not be promoted to a pass/fail scientific claim until the DFT/reference curve
  and discretization sensitivity are available. Numerical quality gates may still predeclare
  finite-difference/grid stability.
- `quality_checks`: at minimum a residual-force gate for relaxation, plus a size/trial check where
  supported.
- `interpretation_guidance`: a successful bounded run may support a trend or screen a candidate; it
  will not establish full reproduction of a paper's headline claim.
- `limitations`: expected risks include MLIP domain shift, finite cell size, reduced sampling, and
  protocol/model mismatch.

## Infrastructure Iterations

- The committed arXiv helper returned valid search metadata, but all three PDF downloads failed:
  two partial-transfer errors (`2602.04861`, `2607.18472`) and one HTTP 429
  (`2603.05238`). Root cause is the helper/arXiv transfer path, not an AtomForge simulation.
  Following the research protocol, the next retrieval attempt uses direct canonical arXiv PDF URLs
  into `/tmp`; no engine fix has been made or hidden.
- Direct arXiv downloads initially failed in the restricted shell because DNS was unavailable.
  Retrying the exact canonical URLs with approved network access succeeded for all three PDFs.
  `pdftotext` extraction then supplied the detailed methods and benchmark values below.
- The first local SCRIPT preflight failed before dispatch with
  `ValueError: zip() argument 2 is shorter than argument 1`. Root cause: three adjacency loops used
  `zip(..., strict=True)` with deliberately shifted lists. The analysis script was corrected to use
  ordinary pairwise zip semantics; no scientific data or acceptance threshold was changed.
- The first Modal command could not connect from the restricted environment. The required
  escalated retry was blocked before upload because explicit approval is required to send the DAG,
  packaged `atomforge/` source, `pyproject.toml`, `uv.lock`, and any configured runtime
  `MP_API_KEY` to Modal. No cloud job was created and no scientific output was produced.
- Before external dispatch, the user correctly identified that
  `bsct_inspired_smoothness.py` was still an ad hoc paper-specific analyzer despite being trusted
  and checked in. It was replaced with reusable `coordinate_scan_analysis.py`. The BSCT citation,
  tungsten coordinate label, symmetry rationale, interpretation, limitations, and report prose now
  live in the DAG configuration rather than generic analyzer code. No metric formula or scientific
  threshold changed.
- The first preflight of the renamed generic analyzer was accidentally run with an empty temporary
  uv cache. That forced a PyPI lookup for already-pinned `pydantic` and failed on restricted DNS.
  This was an environmental invocation error, not a script-contract failure; the documented normal
  uv path was used for the retry.
- After explicit approval, the required Modal dispatch completed without an engine or infrastructure
  failure. The run used the configured `MP_API_KEY` only through the existing AtomForge fetch path;
  no dependency or lockfile change was made for this study.
- The first generic HTML rendering showed `Scientific interpretation: Not recorded` even though the
  SCRIPT bundle contained an incomplete interpretation object. Root cause: the analyzer emitted
  `supported` / `not_supported` / `decision_rule`, while the renderer expected normalized
  `status` / `headline` / `supported_claims` / `limitations`. The generic analyzer and retained
  result now use that single strict contract, and both renderers reject incomplete interpretation
  payloads. No persisted metric or acceptance result changed.

## Research Trace

Primary commands used:

```bash
uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
  --limit 10 --sort relevance \
  'cat:cond-mat.mtrl-sci AND all:"machine learning interatomic potential" AND all:defect'
uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
  --limit 10 --sort relevance \
  'cat:cond-mat.mtrl-sci AND all:"high entropy alloy" AND all:vacancy'
uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
  --download 2602.04861 --dir /tmp/atomforge-arxiv-papers
curl -L --retry 3 --retry-delay 2 \
  -o /tmp/atomforge-arxiv-papers/2602.04861v2.pdf \
  https://arxiv.org/pdf/2602.04861v2
UV_CACHE_DIR=/private/tmp/uv-cache uv run modal run atomforge/platform/modal/deployment.py \
  --spec-path experiments/dags/bsct-inspired-w-smoothness-20260727.json
UV_CACHE_DIR=/private/tmp/uv-cache uv run atomforge report build \
  --experiment-id bsct-inspired-w-smoothness-20260727 --format html
```

The same helper-download/direct-fallback sequence was applied to `2607.18472v1` and
`2603.05238v2`.

| Time (NZST) | Action | Outcome |
|---|---|---|
| 2026-08-01 | Initialized living log before search | Discovery in progress |
| 2026-08-01 | Searched arXiv for MLIP defects, radiation damage, phase transitions, and alloy vacancies | Shortlist identified |
| 2026-08-01 | Downloaded `2602.04861`, `2607.18472`, `2603.05238` with committed helper | Failed: partial transfers / HTTP 429; direct fallback required |
| 2026-08-01 | Directly downloaded canonical PDFs to `/tmp/atomforge-arxiv-papers` and extracted text | Succeeded |
| 2026-08-01 | Triaged claims against current AtomForge observables | BSCT-inspired smoothness probe selected |
| 2026-08-01 | User authorized implementation and execution | DAG/script implementation started |
| 2026-08-01 | Validated DAG and linted analysis script | Passed |
| 2026-08-01 | Preflighted analysis SCRIPT on a harmonic five-point fixture | Failed on strict adjacency zip; fix applied before dispatch |
| 2026-08-01 | Re-ran SCRIPT preflight after the adjacency fix | Passed; exact nine-metric contract matched and harmonic consistency RMSE was `5.36e-11 eV/Å` |
| 2026-08-01 | Ran repository validation before cloud dispatch | `127 passed`; Ruff, DAG validation, and `git diff --check` passed |
| 2026-08-01 | Attempted required Modal dispatch | No job created; external upload awaits explicit informed approval |
| 2026-08-01 | Genericized the analysis component before dispatch | Paper/material semantics moved from script into DAG arguments |
| 2026-08-01 | Ran focused generic-analyzer checks | Two regression tests, Ruff, and full DAG validation passed |
| 2026-08-01 | Preflighted renamed analyzer with an empty temporary uv cache | Dependency lookup blocked by restricted DNS; normal-cache retry required |
| 2026-08-01 | Re-ran generic analyzer preflight through normal uv cache | Passed exact nine-metric contract; analytic consistency RMSE `5.36e-11 eV/Å` |
| 2026-08-01 | Completed post-refactor validation | `129 passed`; Ruff, DAG validation, genericity scan, and `git diff --check` passed |
| 2026-08-01 | Dispatched the ordinary DAG to Modal after explicit approval | Completed successfully; results persisted locally and to the Modal volume |
| 2026-08-01 | Independently recomputed persisted scan diagnostics | Confirmed 21 points, zero extra minima, zero monotonicity violations, `0.0856802 eV/Å` energy-force RMSE, and `12.3152 eV/Å²` maximum adjacent slope change |
| 2026-08-01 | Built the standard bundle-driven HTML report | Wrote `experiments/reports/bsct-inspired-w-smoothness-20260727.html` |
| 2026-08-01 | Audited the generated report's interpretation panel | Replaced the incomplete interpretation payload with the strict report contract; regenerated report records `REVIEW` and the configured claim boundary |
| 2026-08-01 | Validated regenerated HTML against the persisted bundle and rendered page | Passed: three gates and 21 scan rows agree with the bundle; two charts render; source, provenance, and claim boundary are present; desktop/mobile layouts have no page-level overflow or browser console errors |

## Metrics Table

| Candidate / observable | Paper benchmark | AtomForge observable | Triage result |
|---|---:|---:|---|
| BSCT potential-energy-surface smoothness (`2602.04861v2`) | FSD correlated with MD instability; paper Table 1 reports FSD `97.4`, `76.3`, and `43.2 Å⁻¹` for three ablations | Energy/force over a controlled displacement grid; derived discrete curve roughness | **Best immediate fit**, but cross-method and not an exact BSCT reproduction without DFT references |
| FeCrAl vacancy diffusion (`2607.18472v1`) | Cr-rich `Fe15Cr80Al5` activation energy `1.135 eV`; at ~570 K, diffusivity ~`10⁻¹⁷ m²/s` versus ~`10⁻¹³ m²/s` for Fe-rich alloys | Relaxed vacancy formation-energy distribution and optional cascade defect counts | **Interesting applied follow-up**, but current engine cannot test the headline KMC diffusivity claim |
| Charged Sb2Se3 defects (`2603.05238v2`) | Foundation-model relaxed RMSD typically `0.2–0.4 Å` versus a `0.1 Å` identification threshold; charge-aware model reports `<0.05 Å`, `0.48 meV/atom` energy RMSE, `20.15 meV/Å` force RMSE, and transition levels within `0.02 eV` | Neutral structure relaxation only | **High scientific importance, not currently testable**: AtomForge has no charge-state conditioning or HSE reference path |

### Executed BSCT-inspired tungsten scan

Model provenance: MACE-MH-1, `matpes_r2scan` head, float64, checkpoint SHA256
`a522eb7f59c7879963d41586528f4980baf33e086c94aa92e3eafdeccad3be47`.

| Observable / gate | Persisted AtomForge result | Interpretation |
|---|---:|---|
| Reference relaxation maximum force | `1.2344e-14 eV/Å` | Passed declared `<= 0.005 eV/Å` numerical gate |
| Scan completeness | `21 / 21` points | Passed declared workflow gate |
| Maximum inversion-energy mismatch | `7.1054e-15 eV/atom` | Passed declared `<= 0.001 eV/atom` symmetry gate |
| Maximum energy excursion at `|d| = 1 Å` | `0.445865 eV/atom` | Descriptive; energy rises monotonically away from the reference |
| Artificial off-centre minima | `0` | No obvious extra well on this coordinate and grid |
| Outward monotonicity violations | `0` | No reversal on either branch |
| Energy-force consistency RMSE | `0.0856802 eV/Å` | Descriptive finite-difference diagnostic; no paper-derived threshold was assigned |
| Maximum adjacent force-slope change | `12.3152 eV/Å²` | Descriptive grid diagnostic; insufficient alone to label the model smooth or stable |

The energy curve is inversion-symmetric to numerical precision and rises from the relaxed reference
to `445.865 meV/atom` at `±1 Å`. The restoring projected force also changes continuously and
symmetrically, reaching `∓30.7259 eV/Å` at the endpoints. On this bounded coordinate and `0.1 Å`
grid, the scan found no obvious artificial minimum or non-monotonic branch.

### HTML report validation

The regenerated self-contained HTML was checked against
`experiments/results/bsct-inspired-w-smoothness-20260727.json` and rendered in a browser at desktop and mobile
widths:

- the HTML contains the standard doctype, one report body, no external scripts or stylesheets, and
  no browser console errors;
- all three persisted hypotheses appear as `PASSED` with the recorded values;
- both SVG curves render from `smoothness_analysis`, and the evidence table contains all 21
  persisted scan rows;
- the report links arXiv `2602.04861v2`, identifies the source bundle, exposes model/runtime
  details, and states the DFT/FSD claim boundary;
- the top-level status remains `REVIEW`, so passing workflow/numerical gates are not misrepresented
  as paper reproduction or general MLIP validation;
- desktop and mobile layouts have no page-level horizontal overflow. Wide evidence tables use an
  internal horizontal scroller on narrow screens.

## Verification Status

**PASSED for the three predeclared workflow/numerical gates; REVIEW for scientific validation.**

This is a cross-method, one-dimensional screening result. It does not reproduce the paper's
DFT-referenced FSD metric, establish general MACE-MH-1 stability, or replace matched-reference and
bounded-dynamics validation. The justified conclusion is narrower: this tungsten `[111]`
single-atom displacement scan found no obvious pathology under the declared protocol.
