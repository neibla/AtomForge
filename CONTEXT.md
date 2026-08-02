# AtomForge Domain Language

## Scientific decision

The final experiment-authored claim surface. It records one outcome, its exact scope,
calibration status, quality checks, supported claims, and explicit limitations.
`scientific-decision.v1` is the sole persisted contract; stale result bundles are regenerated
instead of supported through runtime compatibility branches.

## Evidence repository

The module that owns experiment-artifact naming, atomic persistence, synchronization, run-state
transitions, and deletion. Local filesystem and Modal volume storage are adapters at this seam.

## Execution profile

The complete Modal policy for one trusted SCRIPT runtime: permitted profile name, image, hardware,
timeout, retry count, concurrency, artifact mount, and commit behavior. A worker may execute only
the profile it declares.

## Evidence chain

The ordered scientific nodes that support a final scientific decision. The UI presents the final
decision first and keeps node-level source, acceptance, and limitation records behind progressive
disclosure.

## Parameter sweep

One logical DAG node that applies a declared coordinate grid to one simulation operation. The
coordinate, unit, parameter binding, bounded point concurrency, failure policy, and representative
visualization trial are part of the persisted contract; individual point jobs remain internal.
