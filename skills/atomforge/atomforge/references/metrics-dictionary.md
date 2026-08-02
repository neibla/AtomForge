# AtomForge Metric Dictionary

When evaluating assertions in a `Hypothesis`, the following metrics are available in the context.

## Node Context Format
Variables are indexed by `{node_id}_{metric}`. Dots in assertions (for example,
`s1.n_defects`) are automatically converted to underscores for evaluation. Simulation metrics
are averaged across declared trials; the report retains the trial samples used for evaluation.

| Metric | Type | Source Node | Description |
| :--- | :--- | :--- | :--- |
| `energy` | float | FETCH | Retrieved reference-structure energy in eV/atom. |
| `n_defects` | float | SIMULATE (`pka`) | Mean periodic vacancy count across declared trials. |
| `interstitials` | float | SIMULATE (`pka`) | Mean periodic interstitial count across declared trials. |
| `energy` | float | SIMULATE (`pka`) | Mean potential energy in eV/atom. |
| `potential_energy` | float | SIMULATE (`relax`, `single_point`, `nvt`) | Mean potential energy in eV/atom. |
| `max_force` | float | SIMULATE (`relax`, `single_point`, `nvt`) | Mean maximum atomic force in eV/Å. |
| `force_norm` | float | SIMULATE (`relax`, `single_point`) | Mean total force-vector norm in eV/Å. |
| `mean_temperature_K` | float | SIMULATE (`nvt`) | Mean sampled temperature in K. |
| `std_temperature_K` | float | SIMULATE (`nvt`) | Temperature standard deviation in K. |
| declared SCRIPT metric | float | SCRIPT | Metric and unit declared by the node's `output_metrics` contract. |

## Aliases
The keyword `target` in an assertion is automatically replaced with the ID of the `target_node` defined in the hypothesis.
Example: `target.n_defects` is resolved to `s1_n_defects` if `target_node="s1"`.
