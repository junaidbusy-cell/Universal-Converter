
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .parser import validate_epub_package
from .extractor import extract_book
from .assets import EPUBAssetManager
from .exporters import export_markdown, export_text, export_json
from .models import BookModel

from common.models import Document
from common.chunker import chunk_document
from common.validator import validate_extraction, validate_output_files, validate_consistency

def process_epub(
    input_path: Union[str, Path],
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    extract_assets: bool = True,
    include_toc: bool = True,
    include_nonlinear: bool = False,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    run_validation: bool = True,
    force: bool = False,
) -> Document:

    start_time = time.time()
    path = Path(input_path).resolve()

    target_out_dir = Path(output_dir) if output_dir else Path("output/EPUB")
    doc_out_dir = target_out_dir / path.stem
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    assets_dir = doc_out_dir / "assets" if extract_assets else None
    asset_mgr = EPUBAssetManager(asset_dir=assets_dir) if extract_assets else None

    zf: zipfile.ZipFile = validate_epub_package(path)

    try:

        book_model: BookModel = extract_book(
            zf=zf,
            source_path=str(path),
            asset_mgr=asset_mgr,
        )

        doc: Document = book_model.to_document(include_nonlinear=include_nonlinear)
    finally:
        try:
            zf.close()
        except Exception:
            pass

    md_content = export_markdown(
        book_model,
        include_frontmatter=True,
        include_toc=include_toc,
        include_nonlinear=include_nonlinear,
    )
    doc.markdown = md_content

    txt_content = export_text(
        book_model,
        include_toc=include_toc,
        include_nonlinear=include_nonlinear,
    )
    doc.text = txt_content

    if enable_chunking:
        doc.chunks = chunk_document(
            doc,
            target_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )

    elapsed = time.time() - start_time
    doc.update_stats()
    doc.stats["processing_time_seconds"] = round(elapsed, 4)

    json_content = export_json(doc, indent=2)

    if run_validation:
        is_valid, val_errors = validate_extraction(doc)
        for err in val_errors:
            doc.add_warning(f"Validation notice: {err}")

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
        has_content = len(doc.blocks) > 0
        file_valid, file_errors = validate_output_files(written_paths, expect_content=has_content)
        for ferr in file_errors:
            doc.add_warning(f"Output file verification notice: {ferr}")

        cons_valid, cons_errors = validate_consistency(doc, md_content, txt_content, json_content)
        for cerr in cons_errors:
            doc.add_warning(f"Consistency notice: {cerr}")

    return doc
