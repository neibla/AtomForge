"""Project-level task entrypoints backed by Poe the Poet."""

import sys

from poethepoet.app import PoeThePoet


def _run_task(name: str) -> None:
    app = PoeThePoet(cwd=None)
    raise SystemExit(app([name] + sys.argv[1:]))


def dev() -> None:
    _run_task("dev")


def deploy() -> None:
    _run_task("deploy-platform")
