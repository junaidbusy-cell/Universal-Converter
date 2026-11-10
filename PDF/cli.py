
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from PDF.pipeline import process_pdf
from PDF.parser import PDFError

def collect_pdf_files(inputs: List[str]) -> List[Path]:

    files: List[Path] = []
    for item in inputs:
        p = Path(item)
        if not p.exists():
            print(f"[WARNING] Path does not exist: {p}", file=sys.stderr)
            continue
        if p.is_file():
            if p.suffix.lower() == ".pdf":
                files.append(p)
            else:
                print(f"[SKIP] Non-PDF file ignored: {p}", file=sys.stderr)
        elif p.is_dir():
            for entry in p.rglob("*.pdf"):
                if entry.is_file():
                    files.append(entry)
    return sorted(list(set(files)))

def process_single_file(pdf_file: Path, args: argparse.Namespace) -> bool:

    t0 = time.time()
    try:
        doc = process_pdf(
            input_path=pdf_file,
            output_format=args.format,
            output_dir=args.output,
            mode=args.mode,
            tier=args.tier,
            dpi=args.dpi,
            engine=args.engine,
            device=args.device,
            lang=args.lang,
            pages=args.pages,
            enable_chunking=not args.no_chunking,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            save_overlay=args.save_overlay,
            force=args.force,
            password=args.password,
        )
        elapsed = time.time() - t0
        print(
            f"[SUCCESS] {pdf_file.name} -> {doc.page_count} pages processed "
            f"({doc.stats.get('character_count', 0)} chars, "
            f"{doc.stats.get('table_count', 0)} tables, "
            f"{doc.stats.get('formula_count', 0)} formulas) in {elapsed:.2f}s"
        )
        return True
    except PDFError as pdf_err:
        print(f"[PDF ERROR] {pdf_file.name}: {pdf_err}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[ERROR] {pdf_file.name}: {exc}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Universal Document Processor - PDF Processing Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--input",
        nargs="+",
        required=True,
        help="Input PDF file(s) or directory paths",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["md", "txt", "json", "all"],
        default="all",
        help="Target output format (default: all)",
    )
    parser.add_argument(
        "-o", "--output",
        default="output/PDF",
        help="Directory to store extracted documents (default: output/PDF)",
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["auto", "native", "ocr", "hybrid", "force-ocr"],
        default="auto",
        help="Extraction mode (default: auto)",
    )
    parser.add_argument(
        "-t", "--tier",
        choices=["tiny", "small", "medium"],
        default="medium",
        help="Model tier for OCR fallback (default: medium)",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Pixmap rendering resolution for OCR in DPI (default: 300)",
    )
    parser.add_argument(
        "--engine",
        choices=["auto", "paddle", "mock", "tesseract"],
        default="auto",
        help="OCR engine implementation (default: auto)",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "gpu:0"],
        default="auto",
        help="Inference device (default: auto)",
    )
    parser.add_argument(
        "-l", "--lang",
        default="en",
        help="OCR primary language code (default: en)",
    )
    parser.add_argument(
        "-p", "--pages",
        help="Selected pages to extract (e.g. '1-3,5')",
    )
    parser.add_argument(
        "--password",
        help="Password for encrypted PDF files",
    )
    parser.add_argument(
        "--save-overlay",
        action="store_true",
        help="Save visual bounding-box overlay PNGs",
    )
    parser.add_argument(
        "--no-chunking",
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
        help="Process multiple PDF files concurrently",
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
    pdf_files = collect_pdf_files(args.input)

    if not pdf_files:
        print("[ERROR] No valid PDF files found.", file=sys.stderr)
        sys.exit(1)

    print(f"[*] Starting PDF processing for {len(pdf_files)} file(s)...")
    start_total = time.time()
    success_count = 0

    if args.parallel and len(pdf_files) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = {executor.submit(process_single_file, f, args): f for f in pdf_files}
            for fut in as_completed(futures):
                if fut.result():
                    success_count += 1
    else:
        for f in pdf_files:
            if process_single_file(f, args):
                success_count += 1

    total_time = time.time() - start_total
    print(f"[*] Completed: {success_count}/{len(pdf_files)} PDF(s) processed in {total_time:.2f}s")
    sys.exit(0 if success_count == len(pdf_files) else 1)

if __name__ == "__main__":
    main()
