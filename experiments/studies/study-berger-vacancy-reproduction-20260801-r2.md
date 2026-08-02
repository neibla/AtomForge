# Berger vacancy reproduction r2 — live validation

**Status:** PASSED (revision 2; bounded workflow claim and presentation artifact)

## Objective

Run and validate `berger-vacancy-reproduction-20260801`: reproduce five frozen
elemental bcc vacancy records from Berger, Bagheri and Komsa (arXiv:2504.06993),
evaluate the identical unrelaxed geometries with MatterSim, and record the
bounded DFT-escalation or no-escalation decision. This is a five-record protocol
reproduction and extension, not a reproduction of the full 86,259-material
campaign or a DFT-validation claim.

## Pre-flight

- Primary source: https://arxiv.org/abs/2504.06993
- Released data: https://zenodo.org/records/15025795 (`Vacancies.json`)
- Intended DAG: `prepare_paper_subset -> {reproduce_mace, evaluate_mattersim} -> select_dft_case`
- Method alignment: `same_method` for the MACE-MP-0 paper subset; `cross_method`
  for the MatterSim extension.
- Declared gates: five selected records, published-data checksum, all five MACE
  reproductions within 0.10 eV, finite MatterSim output for five records, and a
  complete geometry-matched decision panel.

## Infrastructure iterations

1. Updated this checkout from `a363c9f` to merged PR #8, `aeb8ea4`, without
   altering pre-existing unrelated worktree changes.
2. Preflight of the initial draft passed. That superseded DAG was purged after
   revision 2 became the retained demo. It validated the four-node DAG and all
   seven hypotheses without dispatching compute.
3. The analysis SCRIPT was preflighted with an honest five-case upstream-shape
   fixture. Its emitted metric names/units matched the DAG contract and it
   recorded a valid no-escalation decision for the fixture.
4. Focused validation was 26 passed / 1 failed. The failing existing
   `test_script_execution_profile_is_preserved` feeds `FETCH` output into
   `vacancy_formation_energy.py`, which correctly requires a one-trial
   single-point ensemble; the orchestrator reports `PARTIAL`. This test file
   was not changed by PR #8. The four newly added Berger tests passed in the
   same run. No code fix was applied because the requested experiment does not
   use that invalid fixture path.

5. Live Modal dispatch `ap-xPmUCec5sp5c1BIJJ9vQRo` completed with workflow
   status `FAILED`. `prepare_paper_subset` downloaded the expected 378,093,525
   byte source and reached the checksum-verification path, but then called
   `ase.db.connect(...).select()` on the released raw JSON. ASE raised
   `UnknownFileTypeError: Does not resemble ASE JSON database`; all downstream
   nodes were correctly blocked.
6. Retrieved the exact checksum-verified cached source. It is a JSON mapping
   from MP ID to records containing `Symbols`, `Positions`, `Cell`, and
   `Vacancy`, not an ASE JSON database. The five declared records are present;
   for example, `mp-91` has released values `[3.611880302429199,
   3.611880302429199]`. The planned minimal repair is to parse this published
   shape directly, construct an ASE `Atoms` object, and use the explicit
   `Vacancy.<index>` path already declared by the manifest.
7. Applied that repair in `berger_vacancy_protocol.py` and added a fixture test
   for the released MP-keyed JSON shape. Direct parsing of the exact cached
   source now recovers all five frozen records: V 3.0243635, Nb 3.2719440, Ta
   3.7410065, Mo 3.7726583, and W 3.6118803 eV, all with 128-atom pristine
   supercells and minimum repeated-cell lengths above 10 Å. Focused validation
   is 14 passed and scoped Ruff is clean.
8. Created revision 1, `berger-vacancy-reproduction-20260801-r1`, parented to
   the failed revision 0. It changes only the released-data reader; frozen
   records, 0.10 eV reproduction tolerance, model configurations, and 0.25 eV
   escalation rule are unchanged. Its DAG preflight passed.

## Metrics table

| Gate | Declared criterion | Preflight status | Live status |
|---|---|---:|---:|
| DAG shape | four valid SCRIPT nodes, seven valid hypotheses | PASS | r1 PASS |
| Analysis contract | exact declared metrics and units | PASS | r1 PASS |
| Dataset | five records and verified published checksum | PASS locally | r1 PASS |
| MACE reproduction | 5/5 records within 0.10 eV | Pending | r1 PASS: 5/5 |
| MatterSim extension | 5/5 finite evaluations | Pending | r1 PASS: 5/5 |
| Decision | complete, finite, geometry-matched panel | Fixture PASS | r1 PASS: Ta promoted |

### Revision 1 live evidence

| Record | Released vacancy (eV) | MACE paper protocol (eV) | Absolute error (eV) | Result |
|---|---:|---:|---:|---|
| V (`mp-146`) | 3.024364 | 3.022578 | 0.001785 | PASS |
| Nb (`mp-75`) | 3.271944 | 3.268999 | 0.002945 | PASS |
| Ta (`mp-50`) | 3.741006 | 3.740679 | 0.000328 | PASS |
| Mo (`mp-129`) | 3.772658 | 3.774873 | 0.002215 | PASS |
| W (`mp-91`) | 3.611880 | 3.608740 | 0.003140 | PASS |

- Dataset MD5 gate: **PASSED**; persisted source SHA-256:
  `195b0802115adc071b0f79ed3e4819fe2805fcbaae4d61d60ea43f9c72a7213a`.
- MACE reproduction: **5/5 PASSED**, mean absolute error `0.002083 eV`,
  maximum `0.003140 eV` (predeclared tolerance: `0.10 eV`).
- MatterSim extension: **5/5 finite** on geometry fingerprints identical to the
  MACE branch. Maximum single-point force was `0.562777 eV/Å`; this is a
  diagnostic only, not a relaxation/convergence claim.
- Cross-model ranking: Ta (`mp-50`) had the largest self-consistent vacancy
  disagreement, `1.476024 eV`, and was correctly promoted above the declared
  `0.25 eV` threshold. This is a DFT-prioritisation heuristic, not uncertainty
  calibration or a materials-discovery result.

## Post-flight artifact validation

- Modal revision-1 run: `ap-vLlX2rjYTEhbKxz1DnrJQ7`.
- Persisted bundle, Markdown report, visualization catalog, and manifest were
  retrieved under `experiments/results/`; the generic HTML report was rebuilt at
  `experiments/reports/berger-vacancy-reproduction-20260801-r1.html`.
- All seven declared hypotheses are **PASSED** and the persisted workflow status
  is **SUCCESS**.
- The manifest records exact SCRIPT hashes, the dataset hash, MACE-MP-0
  `0.3.15` checkpoint state hash, and MatterSim `1.0.0rc9` checkpoint hash.
- Provenance caveat: because execution was launched from a dirty checkout, the
  manifest records `git_commit: unknown` and `worktree_dirty: true`; artifact
  and script hashes make this run inspectable, but it is not proof of a clean
  committed release. The durable run record also currently omits the r1 parent
  and revision fields, despite the ExperimentSpec containing them.

## Verification status

**PASSED (bounded protocol reproduction and decision workflow).** Revision 1
reproduced the five declared records within the predeclared 0.10 eV tolerance,
evaluated identical geometries with MatterSim, and recorded the predeclared
Ta-to-DFT escalation. This does **not** validate MatterSim against DFT, prove
the full 86,259-material campaign, establish numerical relaxation convergence,
or constitute a materials discovery.

## Visualization revision 2 — in flight

**Objective:** add one inspectable lattice for the demo without introducing a
visual selection bias. The revision will render only the Ta (`mp-50`) frozen
bcc monovacancy because the completed revision-1 decision selected it as the
unique highest eligible MACE–MatterSim disagreement (`1.476024 eV`, above the
predeclared `0.25 eV` DFT-promotion threshold).

**Protocol:** revision 2 parents revision 1 and leaves the source, five-case
panel, model configurations, thresholds, and decision rule unchanged. The
decision node additionally consumes the persisted preparation output and emits
the selected 127-atom vacancy geometry with the removed atom site marked. It
is explicitly labelled a frozen unrelaxed DFT target, not a relaxed DFT result
or a model-validation claim.

**Infrastructure iterations:** local contract validation passed (15 focused
Berger tests and scoped Ruff before dispatch). The decision SCRIPT was also run
against the persisted revision-1 upstream data: it emitted exactly one
`atomistic.v1` visualization, `promoted-bcc-ta-monovacancy`, with 127 Ta atoms
and one vacancy marker. The generic HTML report renderer was extended to draw
recorded vacancy markers as dashed rings, so the self-contained report makes
the defect visible rather than relying on an absent atom at a cell corner.

**Live result:** Modal revision-2 run `ap-TRQsA4NjYiQA3krK304222` completed
with workflow status `SUCCESS`; all seven original scientific hypotheses passed.
Its persisted catalog contains the one Ta bcc monovacancy visual, sourced from
`select_dft_case`. The recorded selection basis is unchanged: Ta is rank 1 with
`1.476024 eV` MACE–MatterSim disagreement over the declared `0.25 eV`
threshold. The artifact records the exact 128-atom pristine / 127-atom defect
counts, vacancy coordinate, geometry fingerprint, and the limitation
`held-out DFT target, not DFT evidence`.

**Verification status:** **PASSED (revision 2 presentation artifact).** The
visualization is a faithful rendering of the frozen geometry selected by the
predeclared decision rule. It does not make the frozen structure a relaxed DFT
result, validate either potential against DFT, or change the scientific scope
of revision 1.
