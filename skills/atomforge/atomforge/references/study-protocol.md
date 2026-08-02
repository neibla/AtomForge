# AtomForge Study Protocol

Use this protocol whenever an agent turns a literature question into an AtomForge experiment.
The objective is an experiment that changes a scientific decision, not merely a valid DAG.

## 1. Classify the latency budget before discovery

Classify the request as a normal study or **live-demo mode**. Live-demo mode permits a smaller
search, a narrower claim, and a bounded runtime; it never changes the requirement for fresh source
discovery, an actual executable run, and persisted evidence.

For every new literature-backed study:

1. Create a distinct `study-<id>.md` before any literature or repository-catalog search.
2. Do not inspect `experiments/dags/`, `experiments/studies/`, reports, or persisted result bundles
   to select the experiment. Discover and select the versioned literature source first.
3. After source selection, existing DAGs and scripts may be used to understand execution contracts.
   Author a new DAG and experiment ID for the new claim; do not relabel a prior result as new
   evidence. In live-demo mode, select the first source whose observable and protocol map directly
   to executable capabilities and stop searching.
4. If no new source can be made executable within the requested demo budget, report that constraint
   and ask for direction. Do not substitute a pre-existing experiment.

## 2. Establish the evidence source

1. Read and follow the committed
   `skills/arxiv-researcher/arxiv-researcher/SKILL.md` skill before searching literature.
2. In the AtomForge checkout, use the committed helper as the primary search path:

   ```bash
   uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
     "<specific materials query>"
   ```

3. If the abstract is insufficient, download the versioned paper into the study-scoped artifact
   directory:

   ```bash
   uv run skills/arxiv-researcher/arxiv-researcher/scripts/search_arxiv.py \
     --download <arxiv-id-or-version> --dir experiments/artifacts/<study-id>/papers
   ```

4. If the helper returns a partial-transfer error or HTTP 429, retry its built-in canonical
   fallback. If retrieval still fails, use the canonical `https://arxiv.org/pdf/<id>` URL with
   bounded retries. Record both failures and fallback commands.
5. Use live web search only as a supplement. Never invent a citation.
6. Record the stable versioned arXiv identifier, canonical URL, actual search/download commands, and the
   extracted benchmark or parameter in `research_trace`.

## 3. Choose a testable claim

- Inspect the checkout and design against capabilities that actually exist.
- Prefer `FETCH -> ALLOY -> SIMULATE -> SCRIPT` when a derived quantity is needed.
- Prefer a reusable SCRIPT analyzer with paper/material semantics supplied through DAG arguments.
  Use paper-specific code only when the computation itself is genuinely unique.
- Do not invent a node type for derived analysis; use a trusted checked-in SCRIPT.
- If AtomForge cannot observe the paper's headline claim, choose a smaller testable claim or label
  the work exploratory. Do not disguise a capability mismatch with a loose threshold.
- Keep a demonstration bounded enough to run interactively unless the user explicitly requests a
  larger study.

## 4. Declare the scientific interpretation contract

Every proposal or study log must state:

1. **Method alignment (`method_alignment`):** `same_method`, `cross_method`, or `unknown`.
2. **Threshold rationale (`threshold_rationale`):** the source or physical reason for every numerical pass/fail boundary.
   Never select a threshold merely because the expected result fits inside it.
3. **Quality checks (`quality_checks`):** at least one numerical-quality or convergence check when the engine can
   support one, such as residual force, cell-size convergence, or ensemble uncertainty.
4. **Interpretation guidance (`interpretation_guidance`):** what a successful run supports and what it does not support.
5. **Limitations (`limitations`):** method mismatch, finite-size effects, sampling limitations, missing physics,
   and model-applicability risks where relevant.

A proposal labelled `scientific_validation` requires `same_method` alignment. A one-trial
cross-method comparison is never a scientific-validation hypothesis. Use hypotheses for
predeclared quality gates; report a paper difference as descriptive evidence unless its acceptance
boundary comes directly from the source.

## 5. Preflight SCRIPT nodes

Before proposing a SCRIPT node:

1. Build a small, honest fixture for its upstream JSON contract in
   `experiments/artifacts/<study-id>/fixtures/`.
2. Run the same checked-in script runner used by the worker:

   ```bash
   uv run atomforge script preflight \
     --script <safe-script-path> \
     --payload <fixture.json> \
     --output-metrics '<json-object>'
   ```

3. Require a successful exit and exact agreement between emitted metric names/units and the
   node's `output_metrics` declaration.
   For `execution_profile: physics_gpu`, include `--execution-profile physics_gpu`; this checks
   `data.model_info` before dispatch and requires an exact checkpoint SHA-256, head, and dtype.
4. Treat preflight as a contract check, not scientific validation. Record it and its limitations.
5. If an honest fixture cannot be constructed or preflight fails, do not silently propose the
   SCRIPT node.

## 6. Build the report from evidence

After a run persists its result bundle:

1. Inspect `results.status`, every `hypotheses[].status`, SCRIPT metrics, and node errors.
2. Inspect the manifest's model checkpoint, head, dtype, source hash, dependency-lock hash, seeds,
   and dirty-worktree state.
3. Independently recompute decision-driving aggregates from persisted rows or trials. Do not rely
   only on a green report.
4. Use the generic report CLI rather than writing an experiment-specific report script:

   ```bash
   uv run atomforge report build --experiment-id <experiment-id> --format html
   ```

5. Inspect the HTML and confirm the verdict, scientific interpretation, source, limitations,
   metrics, and visualization values match the persisted bundle. A missing interpretation is a
   report defect or incomplete contract, not permission to fill the gap with an unsupported claim.

The report command reads `.atomforge/results/<experiment-id>.json` or an explicit `--input` path.
Use `--output` when a different artifact path is required.

## 7. Validate and document

- Validate the complete `ExperimentSpec` with:

  ```bash
  uv run atomforge experiment check --spec-path experiments/dags/<study>.json
  ```

- Use only checked-in SCRIPT paths.
- Maintain the living `experiments/studies/study-<id>.md` record required by `AGENTS.md`.
- Explain before external dispatch that Modal packages source and may use configured secrets.
  Packaging dependency manifests does not imply editing them.
- Preserve the distinction:

  ```text
  workflow execution
          != numerical convergence
          != model applicability
          != scientific validation
  ```

- For an iteration, preserve valid nodes and provenance, make the smallest useful revision, link
  the parent experiment, increment the revision, and explain every changed node.
