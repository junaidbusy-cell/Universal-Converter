
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from WEBPAGE.pipeline import process_webpage
from WEBPAGE.fetcher import DEFAULT_TIMEOUT, MAX_BODY_BYTES, WebpageError

def collect_urls(inputs: List[str]) -> List[str]:

    urls: List[str] = []
    for item in inputs:
        stripped = item.strip()
        if not stripped:
            continue

        p = Path(stripped)
        if p.exists() and p.is_file():
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
                for line in lines:
                    line_clean = line.strip()
                    if line_clean and not line_clean.startswith("#"):
                        urls.append(line_clean)
            except Exception as e:
                print(f"[ERROR] Failed reading URL list from file '{p}': {e}", file=sys.stderr)
            continue

        if stripped.startswith("http://") or stripped.startswith("https://"):
            urls.append(stripped)
        else:

            print(f"[NOTICE] Prepending 'https://' to scheme-less input '{stripped}'", file=sys.stderr)
            urls.append(f"https://{stripped}")

    seen = set()
    deduped = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped

def main():
    parser = argparse.ArgumentParser(
        description="Universal Document Processor - Live Webpage (URL) Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        nargs="+",
        required=True,
        help="Target URL(s) or path to a text file containing URLs",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["md", "txt", "json", "all"],
        default="all",
        help="Target output format (default: all)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output/WEBPAGE",
        help="Directory to store extracted documents (default: output/WEBPAGE)",
    )
    parser.add_argument(
        "--mode",
        choices=["article", "full_page"],
        default="article",
        help="Content extraction mode (default: article)",
    )
    parser.add_argument(
        "--download-assets",
        action="store_true",
        help="Download embedded images into assets/ subfolder",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=700,
        help="Target token chunk size for RAG (default: 700)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=100,
        help="Token overlap between consecutive chunks (default: 100)",
    )
    parser.add_argument(
        "--no-chunks",
        action="store_true",
        help="Disable RAG chunking",
    )
    parser.add_argument(
        "--no-validation",
        action="store_true",
        help="Disable quality and output file validation checks",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite existing output files",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Network request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_BODY_BYTES,
        help=f"Maximum response body cutoff size in bytes (default: {MAX_BODY_BYTES})",
    )
    parser.add_argument(
        "--allow-local",
        action="store_true",
        help="Allow private and loopback addresses (for local testing/mock environments only)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable multi-threaded batch network fetching",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Number of parallel worker threads (default: 4)",
    )

    args = parser.parse_args()

    urls = collect_urls(args.input)
    if not urls:
        print("[ERROR] No valid URLs discovered for processing.", file=sys.stderr)
        sys.exit(1)

    print(f"Discovered {len(urls)} URL(s) for ingestion.")
    print(f"Target format: {args.format} | Output directory: {args.output} | Mode: {args.mode}")

    success_count = 0
    failure_count = 0

    def run_job(target_url: str):
        try:
            doc = process_webpage(
                url=target_url,
                output_format=args.format,
                output_dir=args.output,
                mode=args.mode,
                download_assets=args.download_assets,
                timeout=args.timeout,
                max_bytes=args.max_bytes,
                enable_chunking=not args.no_chunks,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                run_validation=not args.no_validation,
                force=args.force,
                allow_local=args.allow_local,
            )
            duration = doc.stats.get("processing_time_seconds", 0)
            return True, target_url, doc.title, duration
        except WebpageError as err:
            return False, target_url, f"WebpageError: {err}", 0
        except Exception as exc:
            return False, target_url, f"{type(exc).__name__}: {exc}", 0

    if args.parallel and len(urls) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_map = {executor.submit(run_job, u): u for u in urls}
            for future in as_completed(future_map):
                ok, url_str, msg, duration = future.result()
                if ok:
                    success_count += 1
                    print(f"  [OK] {url_str} -> '{msg}' ({duration}s)")
                else:
                    failure_count += 1
                    print(f"  [FAIL] {url_str}: {msg}", file=sys.stderr)
    else:
        for u in urls:
            ok, url_str, msg, duration = run_job(u)
            if ok:
                success_count += 1
                print(f"  [OK] {url_str} -> '{msg}' ({duration}s)")
            else:
                failure_count += 1
                print(f"  [FAIL] {url_str}: {msg}", file=sys.stderr)

    print(f"\nProcessing Complete: {success_count} succeeded, {failure_count} failed.")
    if failure_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
