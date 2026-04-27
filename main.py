"""
main.py — CLI entry points for AtomForge.

Usage:
  uv run atomforge serve         # Start FastAPI server
  uv run atomforge benchmark     # Run local benchmark (no Modal)
  uv run atomforge fetch W Cu    # Fetch and print structures
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def cmd_serve(args):
    import uvicorn

    from atomforge.api import web_app

    uvicorn.run(web_app, host="0.0.0.0", port=8000)


def cmd_benchmark(args):
    from atomforge.benchmark import compute_benchmark, print_benchmark_report
    from atomforge.fetch import fetch_benchmark_set, make_vacancy_supercell
    from atomforge.inference import run_inference_batch

    elements = args.elements or ["W"]
    print(f"Fetching structures: {elements}")
    records = fetch_benchmark_set(elements)

    if args.vacancy:
        print("Creating vacancy supercells…")
        records = [make_vacancy_supercell(r) for r in records]

    print(f"Running MACE-MP-0 ({args.model}) inference locally…")
    results = run_inference_batch(
        [(r.material_id, r.atoms) for r in records],
        model=args.model,
    )

    bm = compute_benchmark(records, results)
    print_benchmark_report(bm)


def cmd_fetch(args):
    from atomforge.fetch import fetch_benchmark_set

    records = fetch_benchmark_set(args.elements or ["W"])
    for r in records:
        print(
            f"{r.formula} ({r.material_id}): {len(r.atoms)} atoms, "
            f"{r.dft_energy_per_atom:.4f} eV/atom DFT"
        )


def main():
    parser = argparse.ArgumentParser(prog="atomforge")
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    sub.add_parser("serve", help="Start FastAPI server")

    # benchmark
    bm = sub.add_parser("benchmark", help="Run local MLIP vs DFT benchmark")
    bm.add_argument("elements", nargs="*", default=["W"])
    bm.add_argument("--model", default="medium", choices=["small", "medium", "large"])
    bm.add_argument("--no-vacancy", dest="vacancy", action="store_false", default=True)

    # fetch
    fe = sub.add_parser("fetch", help="Fetch and print Materials Project structures")
    fe.add_argument("elements", nargs="*", default=["W"])

    args = parser.parse_args()

    match args.command:
        case "serve":
            cmd_serve(args)
        case "benchmark":
            cmd_benchmark(args)
        case "fetch":
            cmd_fetch(args)
        case _:
            parser.print_help()
            sys.exit(1)


if __name__ == "__main__":
    main()
