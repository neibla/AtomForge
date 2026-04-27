# /// script
# dependencies = ["arxiv==3.0.0"]
# ///

import argparse
import json
import os

import arxiv


def search(query, max_results=20, sort_by="relevance", sort_order="descending"):
    """
    Search arXiv with extended options.
    sort_by: relevance, lastUpdatedDate, submittedDate
    sort_order: ascending, descending
    """

    sort_criterion = arxiv.SortCriterion.Relevance
    if sort_by == "lastUpdatedDate":
        sort_criterion = arxiv.SortCriterion.LastUpdatedDate
    elif sort_by == "submittedDate":
        sort_criterion = arxiv.SortCriterion.SubmittedDate

    order = arxiv.SortOrder.Descending
    if sort_order == "ascending":
        order = arxiv.SortOrder.Ascending

    client = arxiv.Client()
    search_query = arxiv.Search(
        query=query, max_results=max_results, sort_by=sort_criterion, sort_order=order
    )

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


def download(arxiv_id, dirpath="."):
    """Download a paper by its arXiv ID."""
    client = arxiv.Client()
    search_query = arxiv.Search(id_list=[arxiv_id])

    try:
        results = list(client.results(search_query))
        if not results:
            return {"status": "error", "message": f"No results found for ID {arxiv_id}"}

        result = results[0]
        # Create directory if it doesn't exist
        os.makedirs(dirpath, exist_ok=True)

        # Download the PDF
        filepath = result.download_pdf(dirpath=dirpath)

        return {
            "status": "success",
            "id": arxiv_id,
            "title": result.title,
            "filename": os.path.basename(filepath),
            "filepath": os.path.abspath(filepath),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
    elif args.query:
        query_str = " ".join(args.query)
        try:
            data = search(
                query_str, max_results=args.limit, sort_by=args.sort, sort_order=args.order
            )
            print(json.dumps(data, indent=2))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
    else:
        parser.print_help()
