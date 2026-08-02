"""AtomForge CLI entry points."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from atomforge.contracts import SCRIPT_EXECUTION_PROFILE_NAMES

load_dotenv()


def cmd_serve(args):
    import uvicorn

    from atomforge.api.http import web_app

    uvicorn.run(web_app, host=args.host, port=args.port)


def cmd_source_check(_args):
    """Compile checked-in runtime sources without importing worker dependencies."""
    from atomforge.validators import validate_runtime_sources

    validate_runtime_sources()
    print("AtomForge Python sources: valid")


def cmd_experiment_check(args):
    """Validate a checked-in experiment and print its execution plan."""
    from atomforge.schemas import ExperimentSpec
    from atomforge.validators import validate_experiment_spec

    spec = ExperimentSpec.model_validate_json(args.spec_path.read_text(encoding="utf-8"))
    validate_experiment_spec(spec)

    print(f"Experiment {spec.experiment_id}: valid")
    for node in spec.dag:
        profile = node.params.get("execution_profile") if node.type == "SCRIPT" else None
        profile_suffix = f" [{profile}]" if profile else ""
        upstream = ", ".join(node.dependencies) if node.dependencies else "root"
        print(f"- {node.id}: {node.type}{profile_suffix} <- {upstream}")
    print(f"Hypotheses: {len(spec.hypotheses)}")
    print("No compute was dispatched.")


def _api_json(
    method: str,
    path: str,
    *,
    api_url: str,
    payload: dict | None = None,
) -> dict | list:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{api_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"AtomForge API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to the AtomForge API at {api_url}: {exc.reason}"
        ) from exc


def cmd_experiment_run(args):
    """Submit through FastAPI so all clients share persistence and recovery."""
    from atomforge.schemas import ExperimentSpec

    spec = ExperimentSpec.model_validate_json(args.spec_path.read_text(encoding="utf-8"))
    response = _api_json(
        "POST",
        "/experiments",
        api_url=args.api_url,
        payload=spec.model_dump(mode="json", exclude={"script_snapshot_id"}),
    )
    print(json.dumps(response, indent=2))


def cmd_experiment_status(args):
    response = _api_json(
        "GET",
        f"/runs/{args.experiment_id}",
        api_url=args.api_url,
    )
    print(json.dumps(response, indent=2))


def cmd_script_preflight(args):
    """Run a checked-in SCRIPT against an honest upstream-contract fixture."""
    from atomforge.execution.script_runner import run_script_node

    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("inputs"), dict):
        raise ValueError("preflight payload must be an object with an 'inputs' object")
    arguments = payload.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("preflight payload 'arguments' must be an object")
    output_metrics = json.loads(args.output_metrics)
    if not isinstance(output_metrics, dict) or not output_metrics:
        raise ValueError("--output-metrics must be a non-empty JSON object")
    result = run_script_node(
        script=args.script,
        inputs=payload["inputs"],
        arguments=arguments,
        output_metrics=output_metrics,
        timeout_seconds=args.timeout_seconds,
        execution_profile=args.execution_profile,
    )
    print(result.model_dump_json(indent=2))


def cmd_report_build(args):
    from atomforge.reporting.html import build_html_report

    output = build_html_report(
        args.experiment_id,
        input_path=args.input,
        output_path=args.output,
    )
    print(f"Wrote {args.format} report: {output}")


def main():
    parser = argparse.ArgumentParser(prog="atomforge")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Start the loopback FastAPI server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    source = sub.add_parser("source", help="Inspect checked-in runtime source")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    source_sub.add_parser("check", help="Compile all checked-in Python source")

    experiment = sub.add_parser("experiment", help="Inspect and submit experiment DAGs")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    experiment_check = experiment_sub.add_parser(
        "check",
        help="Validate a spec and print its execution plan without dispatching compute",
    )
    experiment_check.add_argument(
        "--spec-path",
        type=Path,
        required=True,
        help="Path to a checked-in ExperimentSpec JSON file",
    )
    experiment_run = experiment_sub.add_parser(
        "run",
        help="Submit an experiment through the running AtomForge API",
    )
    experiment_run.add_argument("--spec-path", type=Path, required=True)
    experiment_run.add_argument(
        "--api-url",
        default=os.environ.get("ATOMFORGE_API_URL", "http://127.0.0.1:8000"),
    )
    experiment_status = experiment_sub.add_parser(
        "status",
        help="Read API-owned run status by experiment id",
    )
    experiment_status.add_argument("experiment_id")
    experiment_status.add_argument(
        "--api-url",
        default=os.environ.get("ATOMFORGE_API_URL", "http://127.0.0.1:8000"),
    )

    script = sub.add_parser("script", help="Inspect and test SCRIPT nodes")
    script_sub = script.add_subparsers(dest="script_command", required=True)
    preflight = script_sub.add_parser(
        "preflight",
        help="Run a checked-in SCRIPT against an upstream-contract fixture",
    )
    preflight.add_argument(
        "--script",
        required=True,
        help="Safe path under atomforge/node_scripts",
    )
    preflight.add_argument(
        "--payload",
        type=Path,
        required=True,
        help="JSON file containing {inputs: {...}, arguments: {...}}",
    )
    preflight.add_argument(
        "--output-metrics",
        required=True,
        help='JSON object mapping metric names to units, e.g. \'{"energy":"eV"}\'',
    )
    preflight.add_argument(
        "--execution-profile",
        choices=sorted(SCRIPT_EXECUTION_PROFILE_NAMES),
        default="analysis",
    )
    preflight.add_argument("--timeout-seconds", type=int, default=60)

    report = sub.add_parser("report", help="Build reports from persisted result bundles")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    report_build = report_sub.add_parser(
        "build",
        help="Render an experiment result bundle and its visualization catalog",
    )
    report_build.add_argument("--experiment-id", required=True)
    report_build.add_argument("--format", choices=["html"], default="html")
    report_build.add_argument("--input", type=Path)
    report_build.add_argument("--output", type=Path)

    args = parser.parse_args()
    match args.command:
        case "serve":
            cmd_serve(args)
        case "source":
            cmd_source_check(args)
        case "experiment":
            if args.experiment_command == "check":
                cmd_experiment_check(args)
            elif args.experiment_command == "run":
                cmd_experiment_run(args)
            elif args.experiment_command == "status":
                cmd_experiment_status(args)
        case "script":
            cmd_script_preflight(args)
        case "report":
            cmd_report_build(args)
        case _:
            parser.print_help()
            sys.exit(1)


if __name__ == "__main__":
    main()
