#!/usr/bin/env python3

import argparse
import csv
import io
import os
import re
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

def _get_pipeline_dispatcher():
    from PDF.pipeline import process_pdf
    from DOCX.pipeline import process_docx
    from PPTX.pipeline import process_pptx
    from XLSX.pipeline import process_xlsx
    from EPUB.pipeline import process_epub
    from HTML.pipeline import process_html
    from IMAGE.pipeline import process_image
    from WEBPAGE.pipeline import process_webpage
    from DOI.pipeline import process_doi
    from TEXT.pipeline import process_text
    from DATA.pipeline import process_data

    return {
        "pdf": process_pdf,
        "docx": process_docx,
        "pptx": process_pptx,
        "xlsx": process_xlsx,
        "epub": process_epub,
        "html": process_html,
        "image": process_image,
        "webpage": process_webpage,
        "doi": process_doi,
        "text": process_text,
        "data": process_data,
    }

DOI_REGEX = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$")
DOI_URL_REGEX = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/.+)$", re.IGNORECASE)

def sniff_magic_bytes(data: bytes) -> str:

    if data.startswith(b"%PDF-"):
        return "pdf"

    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff") or data.startswith(b"BM"):
        return "image"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "image"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image"

    if data.startswith(b"{\\rtf"):
        return "docx"

    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
                if any(n.startswith("word/") for n in names):
                    return "docx"
                if any(n.startswith("ppt/") for n in names):
                    return "pptx"
                if any(n.startswith("xl/") for n in names):
                    return "xlsx"
                if any(n.startswith("META-INF/") for n in names) or "mimetype" in names:
                    if "mimetype" in names:
                        mtype = zf.read("mimetype").decode("ascii", errors="ignore")
                        if "opendocument.text" in mtype:
                            return "docx"
                        if "opendocument.spreadsheet" in mtype:
                            return "xlsx"
                        if "opendocument.presentation" in mtype:
                            return "pptx"
                    return "epub"
                if "content.xml" in names:
                    return "docx"
        except Exception:
            pass

    sample = data[:1024].lower()
    if b"<!doctype html" in sample or b"<html" in sample or b"<head" in sample:
        return "html"
    if b"<svg" in sample:
        return "image"
    if b"<?xml" in sample:
        return "data"

    stripped_sample = data[:128].strip()
    if (stripped_sample.startswith(b"{") and b"}" in data) or (stripped_sample.startswith(b"[") and b"]" in data):
        return "data"

    return "unknown"

def sniff_format(item: Union[str, Path]) -> str:

    s = str(item).strip()

    if s.lower().startswith("doi:"):
        return "doi"
    if DOI_URL_REGEX.match(s):
        return "doi"
    if DOI_REGEX.match(s):
        return "doi"

    if s.startswith("http://") or s.startswith("https://"):
        return "webpage"

    p = Path(s)
    if p.is_dir():
        return "directory"

    ext = p.suffix.lower()
    ext_map = {

        ".pdf": "pdf",

        ".docx": "docx",
        ".docm": "docx",
        ".dotx": "docx",
        ".dotm": "docx",
        ".doc": "docx",
        ".dot": "docx",
        ".rtf": "docx",
        ".odt": "docx",

        ".xlsx": "xlsx",
        ".xlsm": "xlsx",
        ".xltx": "xlsx",
        ".xltm": "xlsx",
        ".xls": "xlsx",
        ".xlsb": "xlsx",
        ".ods": "xlsx",

        ".pptx": "pptx",
        ".pptm": "pptx",
        ".ppsx": "pptx",
        ".ppsm": "pptx",
        ".potx": "pptx",
        ".potm": "pptx",
        ".odp": "pptx",
        ".ppt": "pptx",

        ".epub": "epub",
        ".doi": "doi",
        ".url": "webpage",

        ".html": "html",
        ".htm": "html",
        ".xhtml": "html",
        ".mhtml": "html",
        ".mht": "html",

        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".tiff": "image",
        ".tif": "image",
        ".bmp": "image",
        ".webp": "image",
        ".gif": "image",
        ".jfif": "image",
        ".jif": "image",
        ".jpe": "image",
        ".ico": "image",
        ".svg": "image",
        ".avif": "image",
        ".heic": "image",
        ".heif": "image",

        ".txt": "text",
        ".text": "text",
        ".log": "text",
        ".err": "text",
        ".out": "text",
        ".md": "text",
        ".markdown": "text",
        ".mdown": "text",
        ".mkd": "text",
        ".rst": "text",

        ".json": "data",
        ".jsonl": "data",
        ".ndjson": "data",
        ".yaml": "data",
        ".yml": "data",
        ".csv": "data",
        ".tsv": "data",
        ".xml": "data",
        ".toml": "data",
        ".ini": "data",
        ".cfg": "data",
        ".env": "data",
    }
    if ext in ext_map:
        return ext_map[ext]

    if p.is_file():

        try:
            with p.open("rb") as f:
                header_data = f.read(4096)
                magic_fmt = sniff_magic_bytes(header_data)
                if magic_fmt != "unknown":
                    return magic_fmt
        except Exception:
            pass

    return "unknown"

def load_tabular_feed(
    file_path: Union[str, Path],
    delimiter: str = ",",
    url_col: Optional[str] = None,
    doi_col: Optional[str] = None,
    max_rows: Optional[int] = None,
) -> List[str]:

    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(f"Feed file not found: {p}")

    items: List[str] = []
    with p.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter=delimiter)
        rows = [row for row in reader if row]

    if not rows:
        return []

    header = [col.strip().lower() for col in rows[0]]
    col_idx: Optional[int] = None

    if url_col and url_col.lower() in header:
        col_idx = header.index(url_col.lower())
    elif doi_col and doi_col.lower() in header:
        col_idx = header.index(doi_col.lower())
    else:

        candidates = ["url", "doi", "link", "input", "file", "path", "document", "uri"]
        for c in candidates:
            if c in header:
                col_idx = header.index(c)
                break

    start_idx = 1 if col_idx is not None else 0
    target_col = col_idx if col_idx is not None else 0

    for r in rows[start_idx:]:
        if len(r) > target_col:
            val = r[target_col].strip()
            if val:
                items.append(val)

    if max_rows is not None and max_rows > 0:
        items = items[:max_rows]

    return items

def discover_directory_files(
    dir_path: Union[str, Path],
    recursive: bool = False,
    file_type: str = "auto",
) -> List[Path]:

    d = Path(dir_path)
    if not d.is_dir():
        return []

    pattern_fn = d.rglob if recursive else d.glob
    discovered: List[Path] = []
    target_type = file_type.lower() if file_type else "auto"

    for item in pattern_fn("*"):
        if not item.is_file():
            continue

        if item.name.startswith(".") or item.suffix in (".py", ".pyc"):
            continue
        item_fmt = sniff_format(item)
        if target_type != "auto":
            if item_fmt == target_type:
                discovered.append(item)
        else:
            if item_fmt != "unknown" and item_fmt != "directory":
                discovered.append(item)

    return sorted(discovered)

def normalize_ocr_tier(tier: Optional[str]) -> str:

    if not tier:
        return "high"
    t = tier.strip().lower()
    if t in ("mid", "medium"):
        return "medium"
    if t in ("high", "large"):
        return "high"
    if t in ("small",):
        return "small"
    if t in ("tiny",):
        return "tiny"
    return t

def is_hardware_or_ocr_error(exc: Exception) -> bool:

    if isinstance(exc, MemoryError):
        return True
    msg = str(exc).lower()
    keywords = [
        "out of memory",
        "oom",
        "cuda",
        "resource exhausted",
        "failed to allocate",
        "not enough memory",
        "cudnn",
        "memory allocation",
        "failed to initialize paddleocr",
        "device-side assert",
        "hardware limit",
        "insufficient memory",
    ]
    return any(k in msg for k in keywords)

class BatchOCRController:

    TIER_CHAIN = ["high", "medium", "small", "tiny"]

    def __init__(self, initial_tier: str = "high"):
        self._current_tier = normalize_ocr_tier(initial_tier)
        self._lock = threading.Lock()
        self._fallback_history: List[Dict[str, Any]] = []

    @property
    def current_tier(self) -> str:
        with self._lock:
            return self._current_tier

    def get_next_fallback_tier(self, failing_tier: str) -> Optional[str]:
        norm = normalize_ocr_tier(failing_tier)
        if norm in self.TIER_CHAIN:
            idx = self.TIER_CHAIN.index(norm)
            if idx + 1 < len(self.TIER_CHAIN):
                return self.TIER_CHAIN[idx + 1]
        elif norm == "medium":
            return "small"
        elif norm == "small":
            return "tiny"
        return None

    def trigger_fallback(self, failing_tier: str, reason: str = "") -> Optional[str]:
        with self._lock:
            norm_failing = normalize_ocr_tier(failing_tier)
            curr_idx = self.TIER_CHAIN.index(self._current_tier) if self._current_tier in self.TIER_CHAIN else 1
            fail_idx = self.TIER_CHAIN.index(norm_failing) if norm_failing in self.TIER_CHAIN else 1

            if curr_idx > fail_idx:
                return self._current_tier

            next_tier = self.get_next_fallback_tier(self._current_tier)
            if next_tier:
                old_tier = self._current_tier
                self._current_tier = next_tier
                self._fallback_history.append({
                    "from": old_tier,
                    "to": next_tier,
                    "reason": reason,
                    "timestamp": time.time(),
                })
                print(
                    f"\n[!] [OCR CIRCUIT BREAKER] Hardware limit encountered with OCR tier '{old_tier}'. "
                    f"Automatically stepped down to '{next_tier}' for this and all remaining batch items.\n",
                    file=sys.stderr,
                )
                return next_tier
            return None

@dataclass
class ProcessingItemResult:

    item: str
    detected_type: str
    status: str
    elapsed_seconds: float
    title: Optional[str] = None
    word_count: int = 0
    error_message: Optional[str] = None

def process_single_item(
    item: Union[str, Path],
    output_format: str = "md",
    output_dir: Optional[Union[str, Path]] = None,
    force: bool = False,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    input_type: str = "auto",
    extra_options: Optional[Dict[str, Any]] = None,
    dispatchers: Optional[Dict[str, Any]] = None,
    ocr_controller: Optional[BatchOCRController] = None,
) -> ProcessingItemResult:

    t0 = time.time()
    output_format = (output_format or "md").lower()
    item_str = str(item)
    opts = extra_options or {}

    if input_type and input_type.lower() != "auto":
        fmt = input_type.lower()
        if fmt == "markdown":
            fmt = "text"
        elif fmt in ("json", "csv"):
            fmt = "data"
    else:
        fmt = sniff_format(item)

    if fmt == "unknown":
        return ProcessingItemResult(
            item=item_str,
            detected_type="unknown",
            status="FAILED",
            elapsed_seconds=round(time.time() - t0, 3),
            error_message="Unsupported format or file type could not be detected",
        )

    if dispatchers is None:
        dispatchers = _get_pipeline_dispatcher()

    ocr_mode = opts.get("ocr_mode", "auto")
    ocr_lang = opts.get("ocr_lang", "en")

    active_ocr_tier = (
        ocr_controller.current_tier
        if ocr_controller is not None
        else normalize_ocr_tier(opts.get("ocr_tier", "high"))
    )

    while True:
        try:
            pipeline_fn = dispatchers[fmt]

            def _get_title(res: Any, fallback: str = "") -> str:
                t = getattr(res, "title", None)
                if t:
                    return str(t)
                meta = getattr(res, "metadata", None)
                if isinstance(meta, dict):
                    return meta.get("title") or fallback
                if meta and getattr(meta, "title", None):
                    return str(meta.title)
                return fallback

            if fmt == "doi":
                doi_val = item_str
                p_item = Path(item_str)
                if p_item.is_file():
                    for line in p_item.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line_s = line.strip()
                        if line_s and not line_s.startswith("#"):
                            doi_val = line_s
                            break
                result = pipeline_fn(
                    doi=doi_val,
                    output_format=output_format,
                    output_dir=output_dir,
                    force=force,
                    enable_chunking=enable_chunking,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    metadata_only=opts.get("metadata_only", False),
                    access_mode=opts.get("access_mode", "open"),
                    version_preference=opts.get("version_preference", "published"),
                    email=opts.get("email"),
                    client=opts.get("client"),
                    ocr_tier=active_ocr_tier,
                )
                title = _get_title(result, doi_val)
                word_count = result.stats.get("word_count", 0)

            elif fmt == "webpage":
                url_val = item_str
                p_item = Path(item_str)
                if p_item.is_file():
                    for line in p_item.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line_s = line.strip()
                        if line_s and not line_s.startswith("#") and (line_s.startswith("http://") or line_s.startswith("https://")):
                            url_val = line_s
                            break
                result = pipeline_fn(
                    url=url_val,
                    output_format=output_format,
                    output_dir=output_dir,
                    force=force,
                    enable_chunking=enable_chunking,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    mode=opts.get("web_mode", "static"),
                    client=opts.get("client"),
                    allow_local=opts.get("allow_local", False),
                )
                title = _get_title(result, url_val)
                word_count = result.stats.get("word_count", 0)

            elif fmt == "pdf":
                file_path = Path(item)
                result = pipeline_fn(
                    input_path=file_path,
                    output_format=output_format,
                    output_dir=output_dir,
                    force=force,
                    enable_chunking=enable_chunking,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    tier=active_ocr_tier,
                    mode=ocr_mode,
                    lang=ocr_lang,
                )
                title = _get_title(result, file_path.stem)
                word_count = result.stats.get("word_count", 0)

            elif fmt == "image":
                file_path = Path(item)
                result = pipeline_fn(
                    input_path=file_path,
                    output_format=output_format,
                    output_dir=output_dir,
                    force=force,
                    enable_chunking=enable_chunking,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    tier=active_ocr_tier,
                    mode=ocr_mode,
                    lang=ocr_lang,
                )
                title = _get_title(result, file_path.stem)
                word_count = result.stats.get("word_count", 0)

            else:

                file_path = Path(item)
                result = pipeline_fn(
                    input_path=file_path,
                    output_format=output_format,
                    output_dir=output_dir,
                    force=force,
                    enable_chunking=enable_chunking,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                title = _get_title(result, file_path.stem)
                word_count = result.stats.get("word_count", 0)

            elapsed = round(time.time() - t0, 3)
            return ProcessingItemResult(
                item=item_str,
                detected_type=fmt,
                status="SUCCESS",
                elapsed_seconds=elapsed,
                title=title,
                word_count=word_count,
            )

        except Exception as exc:

            if fmt in ("pdf", "image", "doi") and is_hardware_or_ocr_error(exc) and ocr_controller is not None:
                next_tier = ocr_controller.trigger_fallback(active_ocr_tier, reason=str(exc))
                if next_tier and next_tier != active_ocr_tier:
                    active_ocr_tier = next_tier
                    continue

            elapsed = round(time.time() - t0, 3)
            return ProcessingItemResult(
                item=item_str,
                detected_type=fmt,
                status="FAILED",
                elapsed_seconds=elapsed,
                error_message=str(exc),
            )

def print_summary_report(results: List[ProcessingItemResult], total_elapsed: float) -> None:

    border = "=" * 96
    divider = "-" * 96

    print("\n" + border)
    print("           UNIVERSAL DOCUMENT PROCESSOR - BATCH EXECUTION REPORT")
    print(border)
    print(f"{'#':<4} {'Status':<9} {'Type':<9} {'Item':<38} {'Words':<8} {'Time':<8} {'Title'}")
    print(divider)

    succeeded = 0
    failed = 0

    for idx, r in enumerate(results, 1):
        status_str = "[OK]" if r.status == "SUCCESS" else "[FAIL]"
        display_item = Path(r.item).name if (r.item.startswith("/") or "\\" in r.item) else r.item
        item_short = (display_item[:35] + "...") if len(display_item) > 38 else display_item
        title_str = (r.title[:20] + "...") if (r.title and len(r.title) > 23) else (r.title or "-")
        words_str = f"{r.word_count:,}" if r.status == "SUCCESS" else "-"
        time_str = f"{r.elapsed_seconds:.2f}s"

        if r.status == "SUCCESS":
            succeeded += 1
        else:
            failed += 1
            if r.error_message:
                title_str = f"Error: {r.error_message[:20]}"

        print(f"{idx:<4} {status_str:<9} {r.detected_type:<9} {item_short:<38} {words_str:<8} {time_str:<8} {title_str}")

    print(divider)
    print(
        f"Total items: {len(results)} | "
        f"Succeeded: {succeeded} | "
        f"Failed: {failed} | "
        f"Wall time: {total_elapsed:.2f}s"
    )
    print(border + "\n")

def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description="Universal Document Processor - Multi-Format Conversion & Extraction Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export as Markdown (default)
  python main.py -i document.pdf --format md

  # Export all three formats (.md, .txt, .json)
  python main.py -i document.pdf --format all

  # Process a URL or academic DOI
  python main.py -i "https://example.com/article" --format txt
  python main.py -i "10.1038/s41586-020-2649-2" --format all

  # Batch process a directory concurrently
  python main.py -i ./docs/ --recursive --format all --parallel --max-workers 8

  # Batch process from CSV/TSV feeds
  python main.py -c links.csv --url-col url --format all
  python main.py -t papers.tsv --doi-col doi --max-rows 50
        """,
    )

    parser.add_argument(
        "-i", "--input",
        nargs="+",
        help="Input document path(s), URLs, DOIs, or directory paths",
    )
    parser.add_argument(
        "--type", "--input-type",
        dest="input_type",
        type=str.lower,
        choices=[
            "auto", "pdf", "docx", "pptx", "xlsx", "epub", "html", "image",
            "webpage", "doi", "text", "data", "markdown", "json", "csv"
        ],
        default="auto",
        help="Explicitly specify/override input data type (default: auto)",
    )
    parser.add_argument(
        "--format", "-f", "--output-format",
        dest="format",
        type=str.lower,
        choices=["md", "txt", "json", "all"],
        default="md",
        help="Target output data format: md (default), txt, json, or all",
    )
    parser.add_argument(
        "-o", "--output-dir", "--target-dir",
        dest="output_dir",
        help="Target directory to store extracted documents (defaults to output/<FORMAT>/)",
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Recursively scan subdirectories when an input is a directory",
    )
    parser.add_argument(
        "--ocr-model", "--ocr-tier", "--tier",
        dest="ocr_model",
        type=str.lower,
        choices=["tiny", "small", "mid", "medium", "high", "large"],
        default="high",
        help="OCR model performance tier: small, mid/medium, high/large (default), tiny (for IMAGE, PDF, and DOI full-text PDFs)",
    )
    parser.add_argument(
        "--ocr-mode", "--mode",
        dest="ocr_mode",
        type=str.lower,
        choices=["auto", "ocr", "native", "text", "document", "math"],
        default="auto",
        help="OCR extraction mode ('auto', 'ocr', 'native', 'text', 'document', 'math')",
    )
    parser.add_argument(
        "--ocr-lang", "--lang",
        dest="ocr_lang",
        default="en",
        help="Language code for OCR recognition (default: en)",
    )
    parser.add_argument(
        "-c", "--csv",
        help="Path to CSV feed file containing URLs, DOIs, or file paths",
    )
    parser.add_argument(
        "-t", "--tsv",
        help="Path to TSV feed file containing URLs, DOIs, or file paths",
    )
    parser.add_argument(
        "--url-col",
        help="Name of URL column in CSV/TSV feed",
    )
    parser.add_argument(
        "--doi-col",
        help="Name of DOI column in CSV/TSV feed",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        help="Maximum rows to process from CSV/TSV feeds",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Enable multithreaded concurrent batch processing",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Maximum worker threads for parallel execution (default: 4)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output files",
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
        help="Target token size per semantic RAG chunk (default: 700)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=100,
        help="Token overlap between consecutive chunks (default: 100)",
    )
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="DOI only: Retrieve metadata only, skip full-text discovery",
    )

    return parser

def main(argv: Optional[List[str]] = None) -> int:

    parser = build_parser()
    args = parser.parse_args(argv)

    raw_items: List[Union[str, Path]] = []

    if args.input:
        for item in args.input:
            fmt = sniff_format(item)
            if fmt == "directory":
                discovered = discover_directory_files(
                    item,
                    recursive=args.recursive,
                    file_type=args.input_type,
                )
                raw_items.extend(discovered)
            else:
                raw_items.append(item)

    if args.csv:
        csv_items = load_tabular_feed(
            args.csv,
            delimiter=",",
            url_col=args.url_col,
            doi_col=args.doi_col,
            max_rows=args.max_rows,
        )
        raw_items.extend(csv_items)

    if args.tsv:
        tsv_items = load_tabular_feed(
            args.tsv,
            delimiter="\t",
            url_col=args.url_col,
            doi_col=args.doi_col,
            max_rows=args.max_rows,
        )
        raw_items.extend(tsv_items)

    if not raw_items:
        parser.print_help()
        print("\n[ERROR] No input items provided. Specify -i, -c, or -t.", file=sys.stderr)
        return 1

    print(f"[*] Universal Document Processor: {len(raw_items)} item(s) queued for processing.")
    print(
        f"[*] Input Type: '{args.input_type}' | Output Format: '{args.format}' | "
        f"OCR Tier: '{args.ocr_model}' | Parallel: {args.parallel} (workers={args.max_workers})"
    )

    ocr_controller = BatchOCRController(initial_tier=args.ocr_model)

    extra_opts = {
        "metadata_only": args.metadata_only,
        "ocr_mode": args.ocr_mode,
        "ocr_lang": args.ocr_lang,
    }

    t0 = time.time()
    results: List[ProcessingItemResult] = []

    dispatchers = _get_pipeline_dispatcher()

    if args.parallel and len(raw_items) > 1:
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            future_to_item = {
                executor.submit(
                    process_single_item,
                    item,
                    output_format=args.format,
                    output_dir=args.output_dir,
                    force=args.force,
                    enable_chunking=not args.no_chunks,
                    chunk_size=args.chunk_size,
                    chunk_overlap=args.chunk_overlap,
                    input_type=args.input_type,
                    extra_options=extra_opts,
                    dispatchers=dispatchers,
                    ocr_controller=ocr_controller,
                ): item
                for item in raw_items
            }
            for fut in as_completed(future_to_item):
                res = fut.result()
                results.append(res)
    else:
        for item in raw_items:
            res = process_single_item(
                item,
                output_format=args.format,
                output_dir=args.output_dir,
                force=args.force,
                enable_chunking=not args.no_chunks,
                chunk_size=args.chunk_size,
                chunk_overlap=args.chunk_overlap,
                input_type=args.input_type,
                extra_options=extra_opts,
                dispatchers=dispatchers,
                ocr_controller=ocr_controller,
            )
            results.append(res)

    total_elapsed = time.time() - t0
    print_summary_report(results, total_elapsed)

    has_failures = any(r.status == "FAILED" for r in results)
    return 1 if has_failures else 0

if __name__ == "__main__":
    sys.exit(main())
