# AtomForge Metric Dictionary

When evaluating assertions in a `Hypothesis`, the following metrics are available in the context.

## Node Context Format
Variables are indexed by `{node_id}_{metric}`. Dots in assertions (e.g., `s1.avg_defects`) are automatically converted to underscores for evaluation.

| Metric | Type | Source Node | Description |
| :--- | :--- | :--- | :--- |
| `avg_defects` | float | SIMULATE | Mean number of atoms displaced > 1.2Å across ensemble trials. |
| `avg_energy` | float | SIMULATE | Mean potential energy (eV/atom) across the ensemble. |
| `std_defects` | float | SIMULATE | Standard deviation of defect counts. |
| `dft_energy` | float | FETCH | Ground-truth energy per atom from Materials Project. |
| `energy` | float | FETCH | Alias for `dft_energy`. |

## Aliases
The keyword `target` in an assertion is automatically replaced with the ID of the `target_node` defined in the hypothesis.
Example: `target.avg_defects` is resolved to `s1_avg_defects` if `target_node="s1"`.
