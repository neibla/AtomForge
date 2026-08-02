# Codebase Agent Guidelines (`AGENTS.md`)

This document provides context, technical constraints, and developer instructions for AI coding agents developing, refactoring, building, and testing the AtomForge codebase.

For instructions governing **GLaDOS** (the autonomous materials-science researcher conducting experiments and study logs), see [GLaDOS.md](agents/GLaDOS.md). **At the start of every literature-backed materials-science research turn, read `agents/GLaDOS.md` in full before taking any search, design, dispatch, or evidence action.**

---

## Technical Stack & Tooling Constraints

- **Python Environment & Backend**: Use `uv` for all Python package management, environment isolation, and CLI execution.
  - Run tests: `uv run pytest`
  - Run CLI commands: `uv run atomforge ...`
  - Run FastAPI dev server: `uv run uvicorn main:app --reload`
- **Frontend**: Use `bun` for all Node.js package management and script execution.
  - Development server: `bun run dev` (inside `frontend/`)
  - Build frontend: `bun run build` (inside `frontend/`)

---

## Codebase Architecture

```text
AtomForge/
├── agents/          # Agent guidelines and protocols (e.g., GLaDOS.md)
├── atomforge/       # Python backend core, orchestrator, execution engine, and API routes
├── experiments/     # User data & study artifacts (dags, studies, results, reports)
├── frontend/        # React + Vite evidence console UI
├── skills/          # Local agent skills (atomforge, arxiv-researcher)
├── tests/           # Pytest test suite
├── main.py          # FastAPI application entrypoint
└── pyproject.toml   # Python project definition & dependencies (uv managed)
```

---

## Skill Routing Guidelines

AtomForge includes repository-local skills under `skills/` for materials science experiments. 

- **Research-only routing:** The repository name alone is not a trigger to run research skills. Do not invoke it for ordinary FastAPI/API, frontend/UI, platform architecture, worker deployment, infrastructure, refactor, testing, or documentation work.
- Use local research skills (`atomforge`, `arxiv-researcher`) only when explicitly conducting or auditing a materials-science study. Refer to [GLaDOS.md](agents/GLaDOS.md) for research protocols.
