
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from IMAGE.pipeline import process_image
from IMAGE.image_io import SUPPORTED_EXTENSIONS, ImageIOError
from IMAGE.ocr_engine import OCRError

def collect_image_files(inputs: List[str]) -> List[Path]:

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
                print(f"[SKIP] Unsupported image extension: {p}", file=sys.stderr)
        elif p.is_dir():
            for entry in p.rglob("*"):
                if entry.is_file() and entry.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append(entry)
    return sorted(list(set(files)))

def main():
    parser = argparse.ArgumentParser(
        description="Universal Document Processor - Image OCR & Layout Understanding Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        nargs="+",
        required=True,
        help="Input image file(s) or directory paths (PNG, JPG, TIFF, BMP, WebP)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["md", "txt", "json", "all"],
        default="all",
        help="Target output format (default: all)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output/IMAGE",
        help="Directory to store extracted documents (default: output/IMAGE)",
    )
    parser.add_argument(
        "--tier",
        choices=["tiny", "small", "medium"],
        default="medium",
        help="Model performance tier: tiny (~6.6MB), small, medium (~140MB, default)",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "text", "document", "math"],
        default="auto",
        help="Processing mode (default: auto)",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "paddle", "mock", "tesseract"],
        default="auto",
        help="OCR engine implementation (default: auto)",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Execution device: 'auto' (GPU if available, else CPU), 'cpu', 'gpu:0' (default: auto)",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Primary OCR language: 'en', 'hi', 'ch', etc. (default: en)",
    )
    parser.add_argument(
        "--pages",
        default=None,
        help="Page selection for multi-page TIFF (e.g. '1,3,5-8')",
    )
    parser.add_argument(
        "--save-overlay",
        action="store_true",
        help="Save visual bounding-box overlay image in visualization/ directory",
    )
    parser.add_argument(
        "--archive-source",
        action="store_true",
        help="Archive a copy of the raw source image in assets/ subfolder",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        help="Minimum recognition confidence threshold (0.0 - 1.0) to filter noise (default: 0.0)",
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
        help="Enable multi-threaded batch image processing",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Number of parallel worker threads (default: 4)",
    )

    args = parser.parse_args()

    files = collect_image_files(args.input)
    if not files:
        print("[ERROR] No valid image files discovered for processing.", file=sys.stderr)
        sys.exit(1)

    print(f"Discovered {len(files)} image file(s) for processing.")
    print(f"Format: {args.format} | Tier: {args.tier} | Mode: {args.mode} | Output: {args.output}")

    success_count = 0
    failure_count = 0

    def run_job(file_path: Path):
        try:
            doc = process_image(
                input_path=file_path,
                output_format=args.format,
                output_dir=args.output,
                mode=args.mode,
                tier=args.tier,
                engine=args.engine,
                device=args.device,
                lang=args.lang,
                pages=args.pages,
                enable_chunking=not args.no_chunks,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                save_overlay=args.save_overlay,
                archive_source=args.archive_source,
                min_confidence=args.min_confidence,
                run_validation=not args.no_validation,
                force=args.force,
            )
            duration = doc.stats.get("processing_time_seconds", 0)
            page_count = len(doc.pages)
            return True, file_path.name, f"{page_count} page(s)", duration
        except (ImageIOError, OCRError) as err:
            return False, file_path.name, f"{type(err).__name__}: {err}", 0
        except Exception as exc:
            return False, file_path.name, f"{type(exc).__name__}: {exc}", 0

    if args.parallel and len(files) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_map = {executor.submit(run_job, f): f for f in files}
            for future in as_completed(future_map):
                ok, name, msg, duration = future.result()
                if ok:
                    success_count += 1
                    print(f"  [OK] {name} -> {msg} ({duration}s)")
                else:
                    failure_count += 1
                    print(f"  [FAIL] {name}: {msg}", file=sys.stderr)
    else:
        for f in files:
            ok, name, msg, duration = run_job(f)
            if ok:
                success_count += 1
                print(f"  [OK] {name} -> {msg} ({duration}s)")
            else:
                failure_count += 1
                print(f"  [FAIL] {name}: {msg}", file=sys.stderr)

    print(f"\nProcessing Complete: {success_count} succeeded, {failure_count} failed.")
    if failure_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
