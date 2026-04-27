import pytest
from ase import Atoms
from atomforge.simulator import SimulationEngine
from atomforge.schemas import AtomsData, RelaxParams

def test_engine_initialization_and_relax():
    # 1. Setup minimal system (Hydrogen molecule)
    atoms = Atoms('H2', positions=[[0, 0, 0], [0, 0, 0.74]])
    atoms.set_cell([[5, 0, 0], [0, 5, 0], [0, 0, 5]])
    atoms.set_pbc(True)
    
    atoms_data = AtomsData(
        symbols=atoms.get_chemical_symbols(),
        positions=atoms.get_positions().tolist(),
        cell=atoms.get_cell().tolist(),
        pbc=True
    )

    # 2. Initialize engine with 'small' model - handles download/cache
    # This ensures a REAL physics calculation on CPU
    engine = SimulationEngine(model="small", device="cpu")
    
    # 3. Run minimal relaxation
    # Set high fmax for speed (just logic check)
    params = RelaxParams(fmax=0.5)
    result = engine.run(atoms_data, mode="relax", params=params.model_dump())
    
    # 4. Assertions
    # Potential energy for H2 should be negative
    assert result.potential_energy < 0
    assert len(result.positions) == 2
    assert result.runtime_ms > 0

def test_engine_validation_error():
    """Verify the engine raises ValueError for single-atom systems."""
    engine = SimulationEngine(model="small", device="cpu")
    # Correct 3x3 cell matrix
    cell = [[5, 0, 0], [0, 5, 0], [0, 0, 5]]
    atoms_data = AtomsData(
        symbols=["H"],
        positions=[[0, 0, 0]],
        cell=cell,
        pbc=True
    )
    
    with pytest.raises(ValueError, match="requires a supercell with more than 1 atom"):
        engine.run(atoms_data, mode="relax", params={"fmax": 0.5})
