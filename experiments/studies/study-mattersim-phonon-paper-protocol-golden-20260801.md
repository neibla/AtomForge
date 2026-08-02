# MatterSim phonon paper-protocol golden subset — 2026-08-01

## Objective

Create a customer-facing golden MatterSim protocol demo that tests the
published phonon workflow on a small, stable, chemistry-diverse set using the
authors' released protocol rather than a post-hoc selection of low errors.

## Protocol alignment

- Source: Han and Cheng, arXiv:2506.01860,
  https://arxiv.org/abs/2506.01860.
- Exact checkpoint: MatterSim-v1.0.0-5M.
- Six released cases: Al, Cu, Si, GaAs, MgO, NaCl.
- Model supercell: each lattice direction expanded to at least 12 Å, matching
  the authors' released `mlff_phonon_1-5_7_9_10.py`.
- q mesh: each case's `MP` value from `mesh.conf`.
- Fixed-cell FIRE relaxation, `fmax=0.01 eV/Å`, 100-step cap.
- Finite displacement: 0.03 Å.
- Reference: released DFT `FORCE_SETS`, identity conventional-cell mapping.
- Acceptance gates declared before execution: mean MAE < 2 meV, worst MAE < 5
  meV, no DFT or model significant imaginary modes, numerical and batch gates.

## Result

Modal run: `ap-uPGc8SP1ylOLJXvdn3Jxjl`.

| Metric | Result |
|---|---:|
| Cases | 6 |
| Mean phonon-frequency MAE | 1.19580 meV |
| Median phonon-frequency MAE | 1.06735 meV |
| Worst MAE (Si) | 2.29143 meV |
| Model-reference imaginary-mode cases | 0 / 6 |
| DFT-reference imaginary-mode cases | 0 / 6 |
| Maximum residual force | 5.73e-6 eV/Å |
| Batch-equivalence maximum | 1.37e-6 eV/Å |

All declared gates passed. The paper's reported MatterSim global mean is
1.430077 meV over its broader benchmark; the six-case result is a bounded
protocol reproduction, not a replacement for that global statistic.

## Why this is golden

The subset is not chosen by observed MAE. It covers metallic (Al, Cu),
covalent (Si), semiconductor (GaAs), and ionic (MgO, NaCl) crystals, and all
six references are dynamically stable under the declared -1 meV threshold.
The unstable Eu-containing tail is retained in the full archive report as a
separate stress result rather than mixed into this clean headline demo.

## Verification status

**PASSED — bounded protocol smoke test.** This supports the claim that
AtomForge can execute and audit the published MatterSim 5M phonon protocol on
six released, stable, chemistry-diverse crystals with low observed error. It
does not claim full-paper reproduction, a new SOTA result, experimental
neutron-spectrum agreement, or universal accuracy.

## Report presentation correction

The initial HTML structure card showed only the Si conventional base cell
(8 atoms), even though the phonon calculation used the 3×3×3 model supercell
(216 atoms). The report renderer now joins the authoritative per-crystal
comparison row to the atomistic visualization, labels both counts, and expands
the static inspection view to the calculation supercell. The expansion is
explicitly marked visualization-only; it does not alter the persisted result.

The report now includes a paper-to-run mapping panel and the companion evidence
report at `experiments/results/mattersim-phonon-paper-protocol-golden-20260801.md`.
Nominal Materials Project chart labels were given additional axis room so IDs no
longer collide with the x-axis title.

## Editorial hardening — 2026-08-01

The customer-facing golden-demo brief was rewritten after review feedback.
The prior wording was too broad: it described a small subset as a reproduction,
blurred the six-case and 3,008-case populations, and did not explain the old
1.818 meV renderer error. The final brief now:

- labels the six-case result **protocol smoke test — PASS**;
- labels the available-archive result **scale evaluation — COMPLETE · REVIEW**;
- compares both populations directly with the paper's 1.430077 meV MatterSim
  mean, 1.004587 meV median, and 73.417662 meV maximum;
- states that 3,009 archive directories yielded 3,008 valid cases versus the
  paper's 4,869 crystals;
- explains that 1.818 meV was a single-shard renderer bug and 2.010249 meV is
  the authoritative aggregate;
- exposes the scale-run tail instead of presenting the mean as the whole story;
- removes “full SOTA reproduction” language and defines the supported claim as
  protocol execution, provenance, and evidence auditing.

Verification: the brief is documentation-only; the underlying report tests
remain the source of truth for rendering and metric selection.
