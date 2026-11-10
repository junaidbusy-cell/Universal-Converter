
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .parser import load_raw_file, detect_and_decode, parse_html, clean_html, detect_dynamic_content, check_dynamic_indicators
from .extractor import extract_metadata, extract_document
from common.exporters import export_markdown, export_text, export_json
from common.chunker import chunk_document
from common.validator import validate_extraction, validate_output_files, validate_consistency
from common.models import Document

def process_html(
    input_path: Union[str, Path],
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    mode: str = "full_document",
    base_url: Optional[str] = None,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    enable_chunking: bool = True,
    run_validation: bool = True,
    force: bool = False,
) -> Document:

    start_time = time.time()
    path = Path(input_path).resolve()

    raw_bytes = load_raw_file(path)

    decoded_html, encoding, confidence, enc_warnings = detect_and_decode(raw_bytes)

    soup, parser_name, parse_warnings = parse_html(decoded_html)

    meta = extract_metadata(soup, str(path))
    if not meta.charset:
        meta.charset = encoding

    is_spa_candidate = check_dynamic_indicators(soup)

    content_root, clean_warnings = clean_html(soup, mode=mode)

    doc = extract_document(soup, content_root, source_path=str(path), base_url=base_url)
    doc.metadata = meta

    if not doc.title or not doc.title.strip():
        doc.title = path.stem.replace("_", " ").title()

    for w in enc_warnings + parse_warnings + clean_warnings:
        doc.add_warning(w)

    txt_content = export_text(doc)
    doc.text = txt_content

    md_content = export_markdown(doc, include_frontmatter=True)
    doc.markdown = md_content

    if is_spa_candidate and len(doc.text) < 200:
        doc.add_warning(
            f"Document appears to be a client-side rendered Single Page Application (SPA, e.g. React/Vue/Angular). "
            f"Only {len(doc.text)} characters of static content were extracted; complete rendering may require a browser execution engine."
        )

    if enable_chunking:
        doc.chunks = chunk_document(
            doc,
            target_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )

    elapsed = time.time() - start_time
    doc.update_stats()
    doc.stats["processing_time_seconds"] = round(elapsed, 4)
    doc.stats["parser_used"] = parser_name
    doc.stats["detected_encoding"] = encoding
    doc.stats["encoding_confidence"] = confidence

    json_content = export_json(doc, indent=2)

    if run_validation:
        is_valid, val_errors = validate_extraction(doc)
        for err in val_errors:
            doc.add_warning(f"Validation notice: {err}")

    target_out_dir = Path(output_dir) if output_dir else Path("output/HTML")
    doc_out_dir = target_out_dir / path.stem
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    target_format = output_format.lower()
    files_to_write: List[Tuple[str, Path, str]] = []

    if target_format in ("md", "all"):
        files_to_write.append(("md", doc_out_dir / f"{path.stem}.md", md_content))
    if target_format in ("txt", "all"):
        files_to_write.append(("txt", doc_out_dir / f"{path.stem}.txt", txt_content))
    if target_format in ("json", "all"):
        files_to_write.append(("json", doc_out_dir / f"{path.stem}.json", json_content))

    written_paths: List[Path] = []
    for fmt_label, out_file, data_str in files_to_write:
        if out_file.exists() and not force:
            written_paths.append(out_file)
            continue
        out_file.write_text(data_str, encoding="utf-8")
        written_paths.append(out_file)

    if run_validation and written_paths:
        has_content = len(doc.blocks) > 0 or len(raw_bytes) > 0
        file_valid, file_errors = validate_output_files(written_paths, expect_content=has_content)
        for ferr in file_errors:
            doc.add_warning(f"Output file verification notice: {ferr}")

        cons_valid, cons_errors = validate_consistency(doc, md_content, txt_content, json_content)
        for cerr in cons_errors:
            doc.add_warning(f"Consistency notice: {cerr}")

    return doc
