# AtomForge evidence console

This Vite/React application is AtomForge's browser-facing operator console. It creates and monitors experiments through the loopback FastAPI service, renders persisted evidence, and keeps execution status separate from scientific interpretation.

For the complete system boundary, start with the [root README](../README.md). Backend and worker behavior is documented in the [backend README](../atomforge/README.md).

## Architecture

```text
App.tsx
  ├── run list and URL-backed navigation
  ├── experiment composer and graph workspace
  ├── generated TanStack Query hooks ──▶ /api/* ──▶ FastAPI
  ├── handwritten artifact-path adapter ─────────▶ generated blob operation
  ├── lazy visualization host
  │     ├── atomistic / trajectory viewer
  │     ├── charts and tables
  │     └── image artifacts
  └── bundle-driven HTML report
```

The frontend is an evidence reader and operator surface; it is not a second source of scientific truth. Experiment specifications, run states, metrics, hypotheses, provenance, visualization catalogs and report content come from backend contracts or persisted result bundles.

The frontend does not infer scan values from experiment IDs, node IDs, or titles. Structure selectors require authored metadata from the current visualization contract.

### State and data flow

1. `App.tsx` reads the selected experiment and active view from the URL.
2. The run-list query polls every two seconds only while a run is queued or running.
3. Completed and partial runs load their experiment bundle. Report and visualization payloads are fetched only when their views are opened.
4. Experiment creation and rerun submit validated specifications to FastAPI; the browser never calls Modal directly.
5. Visualization artifacts use blob downloads, while normal JSON endpoints use generated hooks.

## Source layout

| Path | Responsibility |
|---|---|
| `src/App.tsx` | Application shell, navigation, query coordination and top-level actions |
| `src/components/ExperimentSidebar.tsx` | Run selection, search and run actions |
| `src/components/ExperimentCreationChooser.tsx` | New-experiment flow and template selection |
| `src/components/ExperimentGraphWorkspace.tsx` | DAG, configuration and recorded evidence inspection |
| `src/components/VisualizationHost.tsx` | Dispatch across typed visualization contracts |
| `src/components/AtomViewer.tsx` | Lazy-loaded Three.js atomistic and trajectory rendering |
| `src/api/default/`, `src/api/model/` | Orval-generated fetchers, hooks and schemas |
| `src/api.ts` | Handwritten visualization artifact helper |
| `src/lib/` | Pure transformations with focused unit tests |

## API contracts

FastAPI's OpenAPI document is the source for normal request and response types:

```bash
bun run api:generate
```

This exports the current schema to `.generated/openapi.json`, then Orval regenerates `src/api/default/` and `src/api/model/`. Generated output is committed and must not be hand-edited.

Normal builds do not regenerate the client. Verify that the committed output matches FastAPI explicitly:

```bash
bun run api:check
```

Handwritten transport code is limited to browser behavior that generated fetchers do not own:

- encoding slash-delimited artifact paths before calling the generated blob operation

Endpoint paths and query parameters come from generated URL builders. Vite owns the single browser-facing origin and proxies `/api/*` to FastAPI after stripping the prefix.

## Local development

From the repository root:

```bash
cd frontend
bun install --frozen-lockfile
bun run dev
```

Open <http://127.0.0.1:5173>. Vite proxies `/api/*` to the local API at `http://127.0.0.1:8000`; start both processes with the root `uv run dev` command when possible.

## Checks

```bash
bun run check
bun run build
```

`bun run check` runs lint, type-checking, unit tests, and generated-client drift verification. `bun run build` type-checks and bundles the already-verified source tree.
