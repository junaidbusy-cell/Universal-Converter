
import sys
import argparse
from pathlib import Path
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from PPTX.pipeline import process_pptx
from PPTX.parser import SUPPORTED_EXTENSIONS

def collect_pptx_files(inputs: List[str]) -> List[Path]:

    files: List[Path] = []
    for item in inputs:
        p = Path(item)
        if not p.exists():
            print(f"[WARNING] Path does not exist: {p}", file=sys.stderr)
            continue
        if p.is_file():
            if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(p)
            else:
                print(f"[SKIP] Unsupported file extension: {p}", file=sys.stderr)
        elif p.is_dir():
            for entry in p.rglob("*"):
                if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append(entry)
    return sorted(list(set(files)))

def main():
    parser = argparse.ArgumentParser(
        description="Universal Document Processor - PPTX Presentation Extraction Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        nargs="+",
        required=True,
        help="Input PPTX file(s) or directory paths",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["md", "txt", "json", "all"],
        default="all",
        help="Target output format (default: all)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output/PPTX",
        help="Directory to store extracted documents (default: output/PPTX)",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="Disable embedded image asset extraction",
    )
    parser.add_argument(
        "--include-hidden-slides",
        action="store_true",
        help="Include hidden slides in readable Markdown and TXT outputs",
    )
    parser.add_argument(
        "--no-notes",
        action="store_true",
        help="Exclude speaker notes from Markdown and TXT outputs",
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
        "--parallel",
        action="store_true",
        help="Enable multi-threaded batch processing",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Number of parallel worker threads (default: 4)",
    )

    args = parser.parse_args()

    files = collect_pptx_files(args.input)
    if not files:
        print("[ERROR] No valid PPTX files discovered for processing.", file=sys.stderr)
        sys.exit(1)

    print(f"Discovered {len(files)} PPTX presentation(s) for processing.")
    print(f"Target format: {args.format} | Output: {args.output}")

    success_count = 0
    failure_count = 0

    def run_job(file_path: Path):
        try:
            doc = process_pptx(
                input_path=file_path,
                output_format=args.format,
                output_dir=args.output,
                extract_assets=not args.no_assets,
                include_hidden_slides=args.include_hidden_slides,
                include_notes=not args.no_notes,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                enable_chunking=not args.no_chunks,
                run_validation=not args.no_validation,
                force=args.force,
            )
            return True, file_path.name, doc.title, doc.stats.get("processing_time_seconds", 0)
        except Exception as exc:
            return False, file_path.name, str(exc), 0

    if args.parallel and len(files) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_map = {executor.submit(run_job, f): f for f in files}
            for future in as_completed(future_map):
                ok, name, msg, duration = future.result()
                if ok:
                    success_count += 1
                    print(f"  [OK] {name} -> '{msg}' ({duration}s)")
                else:
                    failure_count += 1
                    print(f"  [FAIL] {name}: {msg}", file=sys.stderr)
    else:
        for f in files:
            ok, name, msg, duration = run_job(f)
            if ok:
                success_count += 1
                print(f"  [OK] {name} -> '{msg}' ({duration}s)")
            else:
                failure_count += 1
                print(f"  [FAIL] {name}: {msg}", file=sys.stderr)

    print(f"\nProcessing Complete: {success_count} succeeded, {failure_count} failed.")
    if failure_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
