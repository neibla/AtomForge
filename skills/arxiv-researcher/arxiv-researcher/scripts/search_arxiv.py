# /// script
# dependencies = ["arxiv==3.0.0"]
# ///

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


def _load_arxiv():
    import arxiv

    return arxiv


def _canonical_pdf_url(arxiv_id):
    return f"https://arxiv.org/pdf/{quote(arxiv_id, safe='/')}"


def _download_canonical_pdf(arxiv_id, dirpath, attempts=3):
    """Download from arxiv.org with bounded retries and an atomic destination."""
    destination_dir = Path(dirpath)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    last_error = None

    for attempt in range(attempts):
        temporary_path = None
        try:
            request = Request(
                _canonical_pdf_url(arxiv_id),
                headers={"User-Agent": "AtomForge arXiv researcher/1.0"},
            )
            with (
                urlopen(request, timeout=60) as response,
                tempfile.NamedTemporaryFile(
                    dir=destination_dir,
                    prefix=f".{destination.name}.",
                    suffix=".part",
                    delete=False,
                ) as temporary,
            ):
                temporary_path = Path(temporary.name)
                shutil.copyfileobj(response, temporary)

            if temporary_path.stat().st_size < 1024:
                raise RuntimeError("downloaded PDF is unexpectedly small")
            with temporary_path.open("rb") as handle:
                if handle.read(5) != b"%PDF-":
                    raise RuntimeError("downloaded response is not a PDF")

            os.replace(temporary_path, destination)
            return destination.resolve()
        except Exception as exc:
            last_error = exc
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if attempt + 1 < attempts:
                time.sleep(2**attempt)

    raise RuntimeError(
        f"canonical PDF download failed after {attempts} attempts: {last_error}"
    ) from last_error


def search(
    query,
    max_results=20,
    sort_by="relevance",
    sort_order="descending",
    *,
    attempts=3,
    retry_backoff_seconds=3.0,
):
    """
    Search arXiv with extended options.
    sort_by: relevance, lastUpdatedDate, submittedDate
    sort_order: ascending, descending
    """

    arxiv = _load_arxiv()
    sort_criterion = arxiv.SortCriterion.Relevance
    if sort_by == "lastUpdatedDate":
        sort_criterion = arxiv.SortCriterion.LastUpdatedDate
    elif sort_by == "submittedDate":
        sort_criterion = arxiv.SortCriterion.SubmittedDate

    order = arxiv.SortOrder.Descending
    if sort_order == "ascending":
        order = arxiv.SortOrder.Ascending

    search_query = arxiv.Search(
        query=query, max_results=max_results, sort_by=sort_criterion, sort_order=order
    )

    # Keep API pages no larger than the caller's requested result set.  The
    # arxiv library defaults to 100, so a request for --limit 3 otherwise
    # still asks the service for a 100-result page and is more likely to hit
    # transient 503/429 responses.
    page_size = max(1, min(int(max_results), 100))
    last_error = None
    for attempt in range(max(1, attempts)):
        client = arxiv.Client(
            page_size=page_size,
            # Retries are handled here so we can bound the complete command
            # and expose a useful final error rather than nesting retries.
            num_retries=0,
        )
        try:
            results = []
            for result in client.results(search_query):
                results.append(
                    {
                        "id": result.entry_id.split("/")[-1],
                        "title": result.title,
                        "summary": result.summary,
                        "authors": [a.name for a in result.authors],
                        "published": result.published.strftime("%Y-%m-%d"),
                        "updated": result.updated.strftime("%Y-%m-%d"),
                        "pdf_url": result.pdf_url,
                    }
                )
            return results
        except Exception as exc:
            last_error = exc
            if attempt + 1 < max(1, attempts):
                time.sleep(retry_backoff_seconds * (2**attempt))

    raise RuntimeError(
        f"arXiv search failed after {max(1, attempts)} attempts: {last_error}"
    ) from last_error


def download(arxiv_id, dirpath="."):
    """Download by arXiv ID, falling back to the canonical PDF endpoint."""
    arxiv = _load_arxiv()
    client = arxiv.Client()
    search_query = arxiv.Search(id_list=[arxiv_id])
    client_error = None

    try:
        results = list(client.results(search_query))
        if not results:
            raise RuntimeError(f"No results found for ID {arxiv_id}")

        result = results[0]
        os.makedirs(dirpath, exist_ok=True)
        filepath = result.download_pdf(dirpath=dirpath)

        return {
            "status": "success",
            "id": arxiv_id,
            "title": result.title,
            "filename": os.path.basename(filepath),
            "filepath": os.path.abspath(filepath),
            "download_method": "arxiv-client",
        }
    except Exception as exc:
        client_error = str(exc)

    try:
        filepath = _download_canonical_pdf(arxiv_id, dirpath)
        return {
            "status": "success",
            "id": arxiv_id,
            "title": None,
            "filename": filepath.name,
            "filepath": str(filepath),
            "download_method": "canonical-fallback",
            "client_error": client_error,
        }
    except Exception as exc:
        return {
            "status": "error",
            "id": arxiv_id,
            "message": str(exc),
            "client_error": client_error,
            "canonical_url": _canonical_pdf_url(arxiv_id),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search or download arXiv physics papers.")
    parser.add_argument("query", nargs="*", help="The search query")
    parser.add_argument("--limit", type=int, default=20, help="Max results (default 20)")
    parser.add_argument(
        "--sort", choices=["relevance", "lastUpdatedDate", "submittedDate"], default="relevance"
    )
    parser.add_argument("--order", choices=["ascending", "descending"], default="descending")
    parser.add_argument("--download", help="ArXiv ID to download (e.g., '2310.12345')")
    parser.add_argument("--dir", default=".", help="Directory to save the PDF (default '.')")

    args = parser.parse_args()

    if args.download:
        result = download(args.download, dirpath=args.dir)
        print(json.dumps(result, indent=2))
        if result["status"] != "success":
            sys.exit(1)
    elif args.query:
        query_str = " ".join(args.query)
        try:
            data = search(
                query_str, max_results=args.limit, sort_by=args.sort, sort_order=args.order
            )
            print(json.dumps(data, indent=2))
        except Exception as exc:
            print(json.dumps({"error": str(exc)}))
            sys.exit(1)
    else:
        parser.print_help()
