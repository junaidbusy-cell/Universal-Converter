
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image, ImageDraw

from .image_io import (
    validate_image_file,
    iter_image_pages,
    preprocess_image_page,
    map_bbox_to_original,
)
from .ocr_engine import get_ocr_engine, BaseOCREngine
from .extractor import extract_ocr_page
from .models import BoundingBox, OCRRegion, OCRPage, ImageOCRDocument
from .exporters import export_markdown, export_text, export_json

from common.models import Document
from common.chunker import chunk_document
from common.validator import validate_extraction, validate_output_files, validate_consistency

def _render_ocr_overlay(
    image: Image.Image,
    regions: List[OCRRegion],
    output_path: Path,
) -> None:

    overlay_img = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay_img)

    for r in regions:

        outline_color = "#28a745" if r.type == "heading" else ("#fd7e14" if r.type in ("table", "formula") else "#007bff")
        b = r.bbox
        draw.rectangle([b.x1, b.y1, b.x2, b.y2], outline=outline_color, width=2)

        draw.text((b.x1 + 3, b.y1 + 3), str(r.reading_order), fill=outline_color)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_img.save(output_path)

def process_image(
    input_path: Union[str, Path],
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    mode: str = "auto",
    tier: str = "high",
    engine: str = "auto",
    device: str = "auto",
    lang: str = "en",
    pages: Optional[str] = None,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    save_overlay: bool = False,
    archive_source: bool = False,
    min_confidence: float = 0.0,
    run_validation: bool = True,
    force: bool = False,
    mock_regions: Optional[List[OCRRegion]] = None,
) -> ImageOCRDocument:

    start_time = time.time()
    path = validate_image_file(input_path)

    target_out_dir = Path(output_dir) if output_dir else Path("output/IMAGE")
    doc_out_dir = target_out_dir / path.stem
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    ocr_engine: BaseOCREngine = get_ocr_engine(
        engine_name=engine,
        device=device,
        tier=tier,
        lang=lang,
        mock_regions=mock_regions,
    )
    engine_info = ocr_engine.get_engine_info()
    engine_info["mode"] = mode

    processed_pages: List[OCRPage] = []
    first_frame_meta: Dict[str, Any] = {}

    for page_num, raw_frame, frame_meta in iter_image_pages(path, selected_pages=pages):
        if not first_frame_meta:
            first_frame_meta = frame_meta

        preprocessed_img, transforms = preprocess_image_page(raw_frame, preprocess_mode=mode)

        detected_regions = ocr_engine.detect_and_recognize(
            image=preprocessed_img,
            lang=lang,
            tier=tier,
            mode=mode,
        )

        orig_mapped_regions: List[OCRRegion] = []
        for r in detected_regions:
            orig_bbox = map_bbox_to_original(r.bbox, transforms)
            r.bbox = orig_bbox
            orig_mapped_regions.append(r)

        page = extract_ocr_page(
            page_number=page_num,
            raw_regions=orig_mapped_regions,
            page_width=raw_frame.width,
            page_height=raw_frame.height,
            transforms=transforms,
            min_confidence=min_confidence,
        )
        processed_pages.append(page)

        if save_overlay:
            vis_dir = doc_out_dir / "visualization"
            vis_file = vis_dir / f"page_{page_num:03d}_overlay.png" if len(processed_pages) > 1 else vis_dir / "ocr_overlay.png"
            _render_ocr_overlay(raw_frame, page.regions, vis_file)

    doc_metadata = {
        "format": first_frame_meta.get("format", path.suffix.lstrip(".").upper()),
        "width": first_frame_meta.get("width", 0),
        "height": first_frame_meta.get("height", 0),
        "dpi": first_frame_meta.get("dpi"),
        "color_mode": first_frame_meta.get("mode"),
        "file_size_bytes": path.stat().st_size,
    }

    if archive_source:
        assets_dir = doc_out_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest_asset = assets_dir / f"source{path.suffix.lower()}"
        if not dest_asset.exists() or force:
            shutil.copy2(path, dest_asset)
        doc_metadata["asset_path"] = f"assets/{dest_asset.name}"

    ocr_doc = ImageOCRDocument(
        source=str(path),
        source_type="image",
        metadata=doc_metadata,
        ocr_info=engine_info,
        pages=processed_pages,
    )

    txt_content = export_text(ocr_doc)
    ocr_doc.text = txt_content

    md_content = export_markdown(ocr_doc, include_frontmatter=True)
    ocr_doc.markdown = md_content

    doc_bridge: Document = ocr_doc.to_document()
    doc_bridge.text = txt_content
    doc_bridge.markdown = md_content

    if enable_chunking:
        ocr_doc.chunks = chunk_document(
            doc_bridge,
            target_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )
        doc_bridge.chunks = ocr_doc.chunks

    elapsed = time.time() - start_time
    ocr_doc.update_stats()
    ocr_doc.stats["processing_time_seconds"] = round(elapsed, 4)
    doc_bridge.update_stats()
    doc_bridge.stats["processing_time_seconds"] = round(elapsed, 4)

    json_content = export_json(ocr_doc, indent=2)

    if run_validation:
        is_valid, val_errors = validate_extraction(doc_bridge)
        for err in val_errors:
            ocr_doc.add_warning(f"Validation notice: {err}")

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
        has_content = len(ocr_doc.pages) > 0 and any(len(p.regions) > 0 for p in ocr_doc.pages)
        file_valid, file_errors = validate_output_files(written_paths, expect_content=has_content)
        for ferr in file_errors:
            ocr_doc.add_warning(f"Output file verification notice: {ferr}")

        cons_valid, cons_errors = validate_consistency(doc_bridge, md_content, txt_content, json_content)
        for cerr in cons_errors:
            ocr_doc.add_warning(f"Consistency notice: {cerr}")

    return ocr_doc
