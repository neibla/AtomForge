

from __future__ import annotations

import time
from dataclasses import dataclass

import torch
from ase import Atoms
from mace.calculators import mace_mp

# MONKEY-PATCH for Apple Silicon (M1/M2):
# MACE hardcodes .double() (float64) in its forward pass, which MPS doesn't support.
# We override .double() to return .float() (float32) when on an MPS device.
if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
    _orig_double = torch.Tensor.double

    def mps_safe_double(self):
        if self.device.type == "mps":
            return self.float()
        return _orig_double(self)

    torch.Tensor.double = mps_safe_double


@dataclass
class InferenceResult:
    """MLIP prediction for a single structure."""

    material_id: str
    n_atoms: int
    mlip_energy_per_atom: float  # eV/atom
    mlip_forces: list[list[float]]  # (N, 3) eV/Å
    mlip_stress: list[float] | None  # Voigt 6-component, GPa
    runtime_ms: float  # wall-clock inference time


def load_mace_calculator(model: str = "medium", device: str = "auto", dtype: str = "float32"):
    if device == "auto":
        if torch.cuda.is_available():
            device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"

    print(f"Loading MACE-MP-0 ({model}) on {device} with {dtype} precision…")

    if device == "mps":
        calc = mace_mp(model=model, device="cpu", default_dtype="float32")
        if hasattr(calc, "models"):
            for m in calc.models:
                m.to("mps")
        elif hasattr(calc, "model"):
            calc.model.to("mps")
        calc.device = torch.device("mps")
    else:
        calc = mace_mp(model=model, device=device, default_dtype=dtype)

    return calc, device


def run_inference(
    atoms: Atoms,
    material_id: str,
    calculator=None,  # pre-loaded MACE calculator
    model: str = "medium",
    device: str = "auto",
) -> InferenceResult:
    """

    Args:
        atoms: ASE Atoms object.
        material_id: Identifier string for this structure.
        calculator: Pre-loaded MACE calculator (avoids reloading weights each call).
        model: MACE-MP-0 size variant.
        device: Compute device.

    Returns:
        InferenceResult with energies and forces.
    """
    if calculator is None:
        calculator, device = load_mace_calculator(model=model, device=device)

    atoms = atoms.copy()
    atoms.calc = calculator

    t0 = time.perf_counter()
    energy = atoms.get_potential_energy()  # eV
    forces = atoms.get_forces()  # (N, 3) eV/Å
    try:
        stress = atoms.get_stress(voigt=True).tolist()  # GPa
    except Exception:  # noqa: BLE001
        stress = None
    elapsed_ms = (time.perf_counter() - t0) * 1000

    n_atoms = len(atoms)

    return InferenceResult(
        material_id=material_id,
        n_atoms=n_atoms,
        mlip_energy_per_atom=float(energy) / n_atoms,
        mlip_forces=forces.tolist(),
        mlip_stress=stress,
        runtime_ms=elapsed_ms,
    )


def run_inference_batch(
    structures: list[tuple[str, Atoms]],
    model: str = "medium",
    device: str = "auto",
) -> list[InferenceResult]:
    """

    Args:
        structures: List of (material_id, atoms) tuples.
        model: MACE-MP-0 size variant.
        device: Compute device.

    Returns:
        List of InferenceResult objects in the same order.
    """
    calc, device = load_mace_calculator(model=model, device=device)
    print(f"Running batch inference on {len(structures)} structures ({device})…")

    results: list[InferenceResult] = []
    for mid, atoms in structures:
        result = run_inference(atoms, mid, calculator=calc)
        print(f"  {mid}: {result.mlip_energy_per_atom:.4f} eV/atom in {result.runtime_ms:.1f} ms")
        results.append(result)

    return results
