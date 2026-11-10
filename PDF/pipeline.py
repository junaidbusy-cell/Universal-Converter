
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from PIL import Image, ImageDraw

from .parser import (
    validate_pdf_file,
    open_pdf,
    extract_pdf_metadata,
    render_page_pixmap,
    PDFError,
)
from .extractor import extract_page
from .models import PDFDocument, PDFPage, PDFBlock, BoundingBox
from .exporters import export_markdown, export_text, export_json

from common.models import Document
from common.chunker import chunk_document
from common.validator import validate_extraction, validate_output_files, validate_consistency
from IMAGE.ocr_engine import get_ocr_engine, BaseOCREngine

def parse_page_selection(
    pages: Union[str, List[int]],
    total_pages: int,
) -> List[int]:

    if isinstance(pages, list):
        return sorted(list({p for p in pages if 1 <= p <= total_pages}))

    selected: Set[int] = set()
    for part in str(pages).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            try:
                start = int(start_str.strip())
                end = int(end_str.strip())
                for p in range(start, end + 1):
                    if 1 <= p <= total_pages:
                        selected.add(p)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    selected.add(p)
            except ValueError:
                continue

    return sorted(list(selected)) if selected else list(range(1, total_pages + 1))

def _render_pdf_overlay(
    image: Image.Image,
    blocks: List[PDFBlock],
    output_path: Path,
    dpi: int = 300,
) -> None:

    overlay_img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay_img)
    scale = float(dpi) / 72.0

    for b in blocks:
        if not b.bbox:
            continue

        x1 = b.bbox.x1 * scale
        y1 = b.bbox.y1 * scale
        x2 = b.bbox.x2 * scale
        y2 = b.bbox.y2 * scale

        outline_color = (
            "#28a745" if b.type == "heading" else ("#fd7e14" if b.type in ("table", "formula") else "#007bff")
        )
        draw.rectangle([x1, y1, x2, y2], outline=outline_color, width=2)
        draw.text((x1 + 3, y1 + 3), f"{b.reading_order}:{b.source_method[:3]}", fill=outline_color)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_img.save(output_path)

def process_pdf(
    input_path: Union[str, Path],
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    mode: str = "auto",
    tier: str = "high",
    dpi: int = 300,
    engine: str = "auto",
    device: str = "auto",
    lang: str = "en",
    pages: Optional[Union[str, List[int]]] = None,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    save_overlay: bool = False,
    run_validation: bool = True,
    force: bool = False,
    password: Optional[str] = None,
    ocr_engine: Optional[BaseOCREngine] = None,
) -> PDFDocument:

    start_time = time.time()
    path = Path(input_path).resolve()

    doc = open_pdf(path, password=password)
    total_pages = len(doc)

    if output_dir is not None:
        out_base = Path(output_dir)
        doc_out_dir = out_base if out_base.name == path.stem else out_base / path.stem
    else:
        root_dir = Path(__file__).resolve().parent.parent
        doc_out_dir = root_dir / "output" / "PDF" / path.stem
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    if pages is not None:
        target_page_numbers = parse_page_selection(pages, total_pages)
    else:
        target_page_numbers = list(range(1, total_pages + 1))

    effective_ocr_engine = ocr_engine
    if effective_ocr_engine is None:
        effective_ocr_engine = get_ocr_engine(
            engine_name=engine,
            device=device,
            tier=tier,
            lang=lang,
        )

    engine_info = effective_ocr_engine.get_engine_info() if effective_ocr_engine else {}

    pdf_metadata = extract_pdf_metadata(doc)

    extraction_info = {
        "mode": mode,
        "tier": tier,
        "dpi": dpi,
        "engine": engine_info.get("engine", engine),
        "device": engine_info.get("device", device),
        "language": lang,
        "pages_processed": target_page_numbers,
    }

    processed_pages: List[PDFPage] = []
    for p_num in target_page_numbers:
        page = doc[p_num - 1]
        pdf_page = extract_page(
            page=page,
            page_num=p_num,
            mode=mode,
            ocr_engine=effective_ocr_engine,
            dpi=dpi,
            lang=lang,
            tier=tier,
        )
        processed_pages.append(pdf_page)

        if save_overlay:
            vis_dir = doc_out_dir / "visualization"
            vis_file = (
                vis_dir / f"page_{p_num:03d}_overlay.png"
                if len(target_page_numbers) > 1
                else vis_dir / "pdf_overlay.png"
            )
            raw_img = render_page_pixmap(page, dpi=dpi)
            _render_pdf_overlay(raw_img, pdf_page.blocks, vis_file, dpi=dpi)

    doc.close()

    pdf_doc = PDFDocument(
        source=str(path),
        page_count=len(processed_pages),
        metadata=pdf_metadata,
        extraction_info=extraction_info,
        pages=processed_pages,
    )

    txt_content = export_text(pdf_doc)
    pdf_doc.text = txt_content

    md_content = export_markdown(pdf_doc, include_frontmatter=True)
    pdf_doc.markdown = md_content

    doc_bridge: Document = pdf_doc.to_document()
    doc_bridge.text = txt_content
    doc_bridge.markdown = md_content

    if enable_chunking:
        pdf_doc.chunks = chunk_document(
            doc_bridge,
            target_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )
        doc_bridge.chunks = pdf_doc.chunks

    elapsed = time.time() - start_time
    pdf_doc.update_stats()
    pdf_doc.stats["processing_time_seconds"] = round(elapsed, 4)
    doc_bridge.update_stats()
    doc_bridge.stats["processing_time_seconds"] = round(elapsed, 4)

    json_content = export_json(pdf_doc, indent=2)

    if run_validation:
        is_valid, val_errors = validate_extraction(doc_bridge)
        for err in val_errors:
            pdf_doc.add_warning(f"Validation notice: {err}")

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
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(data_str, encoding="utf-8")
        written_paths.append(out_file)

    if run_validation and written_paths:
        has_content = len(pdf_doc.pages) > 0 and any(len(p.blocks) > 0 for p in pdf_doc.pages)
        file_valid, file_errors = validate_output_files(written_paths, expect_content=has_content)
        for ferr in file_errors:
            pdf_doc.add_warning(f"Output file verification notice: {ferr}")

        cons_valid, cons_errors = validate_consistency(doc_bridge, md_content, txt_content, json_content)
        for cerr in cons_errors:
            pdf_doc.add_warning(f"Consistency notice: {cerr}")

    return pdf_doc
