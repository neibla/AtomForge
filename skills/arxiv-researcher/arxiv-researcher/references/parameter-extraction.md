# Extraction Patterns for Physics Research

Record the value, unit, source location (section/table/figure), and whether it is directly compatible
with the intended AtomForge observable.

## 1. Material Properties

- **Lattice Parameters:** Look for "lattice constant", "a =", "b =", "c =" (usually in Angstroms Å).
- **Crystal Structure:** Identify "BCC", "FCC", "HCP", or specific space groups.
- **Formation Energy:** Look for "E_form", "eV/atom", or "vacancy formation energy".
- **Composition and Cell:** Record stoichiometry, atom count, supercell transformation, periodicity,
  and charge state.

## 2. Simulation Constraints

- **Potential Model:** Identify the MLIP used (e.g., "MACE-MP-0", "EquiformerV2", "CHGNet").
- **Supercell Size:** Look for dimensions like "3x3x3", "N=1000 atoms", or "periodic boundary conditions".
- **Defect Thresholds:** Look for displacement values (e.g., "1.2 Å threshold for defect identification").
- **Protocol:** Record relaxation optimizer and force threshold, ensemble, timestep, thermostat,
  duration, sampling interval, seeds/trials, and finite-size or convergence checks.

## 3. Benchmarks

- **RMSE/MAE:** Note the reported Energy RMSE (meV/atom) and Force RMSE (meV/Å).
- **DFT Code:** Check if they used VASP, Quantum Espresso, or CP2K as the reference.
- **Electronic Structure:** Record functional, pseudopotential/basis, cutoff, k-point mesh, spin,
  dispersion, charge correction, and convergence settings when relevant.
- **Statistics:** Record dataset split, sample size, uncertainty/error bars, aggregation, and
  normalization.

## 4. Compatibility Decision

Classify the proposed comparison:

- `same_method`: matched model/reference and protocol;
- `cross_method`: observable is comparable but method or model differs;
- `unknown`: source detail is insufficient.

If AtomForge lacks the paper's charge state, DFT setup, long-timescale dynamics, or target
observable, choose a smaller exploratory claim and state the mismatch explicitly.
