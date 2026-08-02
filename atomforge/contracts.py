from typing import Literal, get_args

NodeType = Literal["FETCH", "ALLOY", "SIMULATE", "SWEEP", "SCRIPT"]
SimulationMode = Literal["pka", "relax", "single_point", "nvt"]
ScriptExecutionProfile = Literal["analysis", "physics_gpu", "dft_cpu", "dft_gpu"]

NODE_TYPES = frozenset(get_args(NodeType))
SIMULATION_MODES = frozenset(get_args(SimulationMode))
SCRIPT_EXECUTION_PROFILE_NAMES = frozenset(get_args(ScriptExecutionProfile))
RESERVED_SCRIPT_ARGUMENTS = frozenset({"fixture_results"})
MAX_VISUALIZATION_CATALOG_ITEMS = 10_000
MAX_SWEEP_POINT_ERROR_LENGTH = 2_000
MAX_SIMULATION_TRIALS = 100
SWEEP_METRIC_NAMES = frozenset({"sample_count", "completed_count", "failed_count"})
