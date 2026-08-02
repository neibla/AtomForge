# AtomForge

Materials Science Research Platform (PoC)

> *"You just keep on trying till you run out of cake. And the Science gets done."*
> — **GLaDOS**, autoresearcher

## Components

### GLaDOS research agent

**Purpose:** Autonomously researches scientific questions, designs experiments, analyses evidence and draws conclusions.

**How:** Plugs into compatible agents such as Codex. It uses reusable skills to research literature and create, execute and evaluate experiment DAGs through the AtomForge CLI.

**Technology:** Codex or another skill-compatible agent, the arXiv research skill, the AtomForge skill and the AtomForge CLI.

**Repository surface:** `agents/GLaDOS.md` defines the operating protocol, `skills/` provides the reusable research skills, `main.py` exposes the `atomforge` CLI handoff, and `experiments/` stores study records and authored DAGs. GLaDOS is an external research-agent integration; it is not a Python worker or a second execution runtime.

### AtomForge application

**Purpose:** Enables researchers to create experiments and understand their results.

**How:** Provides DAG authoring and execution alongside experiment results, visualizations, reports and conclusions. FastAPI generates the OpenAPI contract used to produce the frontend's typed API client.

**Technology:** React, Vite, FastAPI, OpenAPI and Orval.

### Execution platform

**Purpose:** Executes scientific DAGs using the compute required by each workload.

**How:** Orchestrates dependencies, routes tasks to CPU or GPU workers, tracks failures and persists the resulting artifacts.

**Technology:** `CoreOrchestrator`, Modal, on-demand CPU/GPU workers, Modal Volumes and persistent result storage.

- [Frontend architecture](frontend/README.md)
- [Backend and execution architecture](atomforge/README.md)
- [GLaDOS operating contract](agents/GLaDOS.md)

## Local setup

Prerequisites:

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- [Bun](https://bun.sh/)
- Modal authentication for remote execution

Install the locked environments:

```bash
uv sync --frozen --extra dev --extra physics
cd frontend && bun install --frozen-lockfile && cd ..
```

Start FastAPI and Vite together:

```bash
uv run dev
```

Open <http://127.0.0.1:5173>. Vite is the browser-facing origin and proxies `/api/*` to the loopback API on `127.0.0.1:8000`.

## Validate and run an experiment

Compile checked-in Python source explicitly:

```bash
uv run atomforge source check
```

Validate a checked-in DAG without dispatching compute:

```bash
uv run atomforge experiment check \
  --spec-path experiments/dags/<experiment>.json
```

Submit through the running API:

```bash
uv run atomforge experiment run \
  --spec-path experiments/dags/<experiment>.json

uv run atomforge experiment status <experiment-id>
```

Build a report from the persisted result bundle:

```bash
uv run atomforge report build \
  --experiment-id <experiment-id> \
  --format html
```

## Deploy private workers

Deploy only the worker application:

```bash
uv run deploy
```

The command expands to the pinned deployment task, entrypoint
`atomforge/platform/modal/deployment.py`, and the `atomforge-workers` production name.

The local API resolves `atomforge-workers/Orchestrator` through the authenticated Modal SDK.


## Checks

```bash
uv run atomforge source check
uv run pytest -q
uv run ruff check atomforge main.py tests

cd frontend
bun run check
bun run build
```