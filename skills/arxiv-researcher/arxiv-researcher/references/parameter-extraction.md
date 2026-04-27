# Extraction Patterns for Physics Research

When exploring arXiv papers for AtomForge, focus on extracting these specific parameters to ground the simulations.

## 1. Material Properties
- **Lattice Parameters:** Look for "lattice constant", "a =", "b =", "c =" (usually in Angstroms Å).
- **Crystal Structure:** Identify "BCC", "FCC", "HCP", or specific space groups.
- **Formation Energy:** Look for "E_form", "eV/atom", or "vacancy formation energy".

## 2. Simulation Constraints
- **Potential Model:** Identify the MLIP used (e.g., "MACE-MP-0", "EquiformerV2", "CHGNet").
- **Supercell Size:** Look for dimensions like "3x3x3", "N=1000 atoms", or "periodic boundary conditions".
- **Defect Thresholds:** Look for displacement values (e.g., "1.2 Å threshold for defect identification").

## 3. Benchmarks
- **RMSE/MAE:** Note the reported Energy RMSE (meV/atom) and Force RMSE (meV/Å).
- **DFT Code:** Check if they used VASP, Quantum Espresso, or CP2K as the reference.
- **Pseudopotentials:** Note the specific PBE/LDA functional used.
