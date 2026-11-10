
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from DOI.pipeline import process_doi
from DOI.resolver import is_valid_doi, normalize_doi

def process_single_doi(doi_str: str, args: argparse.Namespace) -> bool:

    t0 = time.time()
    try:
        paper = process_doi(
            doi=doi_str,
            output_format=args.format,
            output_dir=args.output,
            metadata_only=args.metadata_only,
            access_mode=args.access_mode,
            version_preference=args.version_preference,
            email=args.email,
            enable_chunking=not args.no_chunks,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            force=args.force,
        )
        elapsed = time.time() - t0
        print(
            f"[SUCCESS] {paper.doi} -> '{paper.title[:50]}...' "
            f"({paper.access.full_text_status}, {paper.stats.get('word_count', 0)} words, "
            f"{paper.stats.get('section_count', 0)} sections) in {elapsed:.2f}s"
        )
        return True
    except Exception as exc:
        print(f"[ERROR] {doi_str}: {exc}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Universal Document Processor - DOI Academic Paper Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        nargs="+",
        required=True,
        help="Input DOI string(s) or canonical DOI URLs",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["md", "txt", "json", "all"],
        default="all",
        help="Target output format (default: all)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output/DOI",
        help="Directory to store extracted documents (default: output/DOI)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Retrieve metadata only, skip full-text discovery",
    )
    parser.add_argument(
        "--access-mode",
        choices=["open", "authorized", "metadata"],
        default="open",
        help="Access authorization mode (default: open)",
    )
    parser.add_argument(
        "--version-preference",
        choices=["published", "accepted", "any"],
        default="published",
        help="Article version preference (default: published)",
    )
    parser.add_argument(
        "--email",
        help="Contact email for polite API access (Crossref, Unpaywall, OpenAlex)",
    )
    parser.add_argument(
        "--no-chunks",
        action="store_true",
        help="Disable semantic RAG chunking",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=700,
        help="RAG chunk target token size (default: 700)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=100,
        help="RAG chunk overlap tokens (default: 100)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Process multiple DOIs concurrently",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum thread workers for parallel processing (default: 4)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files",
    )

    args = parser.parse_args()
    dois = [normalize_doi(d) for d in args.input]

    print(f"[*] Starting DOI processing for {len(dois)} publication(s)...")
    start_total = time.time()
    success_count = 0

    if args.parallel and len(dois) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {executor.submit(process_single_doi, d, args): d for d in dois}
            for fut in as_completed(futures):
                if fut.result():
                    success_count += 1
    else:
        for d in dois:
            if process_single_doi(d, args):
                success_count += 1

    total_time = time.time() - start_total
    print(f"[*] Completed: {success_count}/{len(dois)} publication(s) processed in {total_time:.2f}s")
    sys.exit(0 if success_count == len(dois) else 1)

if __name__ == "__main__":
    main()
