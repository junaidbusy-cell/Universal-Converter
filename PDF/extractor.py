
import io
from pathlib import Path
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

fitz = pymupdf

from IMAGE.models import BoundingBox, OCRRegion
from IMAGE.ocr_engine import BaseOCREngine, get_ocr_engine
from IMAGE.extractor import detect_columns, reconstruct_reading_order, reconstruct_paragraphs
from .models import PDFBlock, PDFTable, PDFFormula, PDFImage, PDFPage
from .parser import render_page_pixmap, bbox_px_to_pdf_points, extract_page_images

def classify_pdf_page(page: pymupdf.Page) -> Tuple[str, List[str]]:

    reasons: List[str] = []
    text = page.get_text("text").strip()
    char_count = len(text)

    page_w = page.rect.width
    page_h = page.rect.height
    page_area = max(1.0, page_w * page_h)

    images = page.get_images(full=True)
    img_area = 0.0
    for img_info in images:
        xref = img_info[0]
        rects = page.get_image_rects(xref)
        for r in rects:
            img_area += r.width * r.height

    image_coverage = min(1.0, img_area / page_area)

    if char_count > 20:

        replacement_count = text.count("\ufffd") + (text.count("·") if text.count("·") > 3 else 0)

        non_printable = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
        total_bad = replacement_count + non_printable
        bad_ratio = total_bad / float(char_count)

        if bad_ratio > 0.15:
            reasons.append(
                f"High replacement / corrupt character ratio ({bad_ratio:.1%}, {total_bad}/{char_count} chars)"
            )
            return "poor_text", reasons

    if char_count == 0 and (len(images) == 0 or image_coverage < 0.03):
        reasons.append(f"No selectable text ({char_count} chars) and negligible image coverage ({image_coverage:.1%})")
        return "blank", reasons

    if char_count < 25 and (len(images) == 0 or image_coverage < 0.05):
        reasons.append(f"Sparse whitespace-only content ({char_count} chars)")
        return "blank", reasons

    if char_count < 50 and (len(images) > 0 and image_coverage >= 0.35):
        reasons.append(
            f"Minimal native text ({char_count} chars) with dominant image coverage ({image_coverage:.1%}, {len(images)} images)"
        )
        return "scanned", reasons

    if char_count >= 100 and image_coverage >= 0.10 and len(images) >= 1:
        reasons.append(
            f"Substantial native text ({char_count} chars) combined with prominent image coverage ({image_coverage:.1%})"
        )
        return "hybrid", reasons

    if char_count >= 50:
        reasons.append(f"Selectable text stream with healthy font encodings ({char_count} chars)")
        return "digital", reasons

    if image_coverage >= 0.35:
        reasons.append(f"Predominant image coverage ({image_coverage:.1%})")
        return "scanned", reasons

    reasons.append(f"Standard selectable digital text ({char_count} chars)")
    return "digital", reasons

def compute_body_font_size(page: pymupdf.Page) -> float:

    counts: Counter = Counter()
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if block.get("type") == 0:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if span_text:
                        size = round(span.get("size", 10.0), 1)
                        counts[size] += len(span_text)

    if counts:
        return counts.most_common(1)[0][0]
    return 10.5

def _is_math_formula(text: str) -> bool:

    cleaned = text.strip()
    if not cleaned:
        return False
    if cleaned.startswith("$$") and cleaned.endswith("$$"):
        return True
    if cleaned.startswith("$") and cleaned.endswith("$") and len(cleaned) > 2:
        return True
    math_tokens = (
        "\\begin{equation}",
        "\\frac",
        "\\sqrt",
        "\\sum",
        "\\int",
        "\\partial",
        "\\alpha",
        "\\beta",
        "\\gamma",
        "\\theta",
        "\\lambda",
        "\\sigma",
        "\\omega",
        "±",
        "≠",
        "≤",
        "≥",
        "≈",
        "∈",
        "∑",
        "∫",
        "√",
    )
    return any(tok in cleaned for tok in math_tokens)

def extract_native_tables(page: pymupdf.Page, page_num: int) -> List[PDFTable]:

    extracted_tables: List[PDFTable] = []
    tab_idx = 1

    try:
        table_finder = page.find_tables()
        for tab in table_finder.tables:
            raw_matrix = tab.extract()
            if not raw_matrix or len(raw_matrix) == 0:
                continue

            matrix: List[List[str]] = []
            for row in raw_matrix:
                cleaned_row = [str(c).strip() if c is not None else "" for c in row]
                matrix.append(cleaned_row)

            headers = matrix[0] if matrix else []
            rows = matrix[1:] if len(matrix) > 1 else []

            tb_bbox = BoundingBox(
                x1=round(tab.bbox[0], 2),
                y1=round(tab.bbox[1], 2),
                x2=round(tab.bbox[2], 2),
                y2=round(tab.bbox[3], 2),
            )

            extracted_tables.append(
                PDFTable(
                    table_id=f"tab_p{page_num}_{tab_idx}",
                    page_number=page_num,
                    headers=headers,
                    rows=rows,
                    bbox=tb_bbox,
                    source_method="native",
                    confidence=1.0,
                )
            )
            tab_idx += 1
    except Exception:

        try:
            import pdfplumber
            doc_path = page.parent.name
            if doc_path and Path(doc_path).exists():
                with pdfplumber.open(doc_path) as pdf:
                    if page_num - 1 < len(pdf.pages):
                        plumb_page = pdf.pages[page_num - 1]
                        plumb_tabs = plumb_page.extract_tables()
                        for ptab in plumb_tabs:
                            if ptab:
                                headers = [str(c).strip() if c else "" for c in ptab[0]]
                                rows = [[str(c).strip() if c else "" for c in r] for r in ptab[1:]]
                                extracted_tables.append(
                                    PDFTable(
                                        table_id=f"tab_p{page_num}_{tab_idx}",
                                        page_number=page_num,
                                        headers=headers,
                                        rows=rows,
                                        source_method="native",
                                        confidence=0.95,
                                    )
                                )
                                tab_idx += 1
        except Exception:
            pass

    return extracted_tables

def sort_pdf_blocks_reading_order(
    blocks: List[PDFBlock],
    page_width: float,
) -> List[PDFBlock]:

    if len(blocks) <= 1:
        return blocks

    regions = [
        OCRRegion(
            region_id=b.block_id,
            type=b.type,
            text=b.text,
            bbox=b.bbox if b.bbox else BoundingBox(0, 0, 0, 0),
            extra={"orig_block": b},
        )
        for b in blocks
    ]
    sorted_regions = reconstruct_reading_order(regions, page_width=int(page_width))
    ordered_blocks: List[PDFBlock] = []
    for idx, r in enumerate(sorted_regions):
        orig_b = r.extra["orig_block"]
        orig_b.reading_order = idx + 1
        ordered_blocks.append(orig_b)
    return ordered_blocks

def extract_native_page(
    page: pymupdf.Page,
    page_num: int,
) -> Tuple[List[PDFBlock], List[PDFTable], List[PDFFormula], List[PDFImage]]:

    body_size = compute_body_font_size(page)
    tables = extract_native_tables(page, page_num)
    page_images_meta = extract_page_images(page)

    pdf_images: List[PDFImage] = []
    for img_dict in page_images_meta:
        pdf_images.append(
            PDFImage(
                image_id=img_dict["image_id"],
                page_number=page_num,
                bbox=img_dict["bbox"],
                width_px=img_dict["width_px"],
                height_px=img_dict["height_px"],
                format=img_dict["format"],
            )
        )

    text_dict = page.get_text("dict")
    raw_blocks = text_dict.get("blocks", [])

    blocks: List[PDFBlock] = []
    formulas: List[PDFFormula] = []
    block_idx = 1
    formula_idx = 1

    for b in raw_blocks:
        if b.get("type") != 0:
            continue

        lines = b.get("lines", [])
        if not lines:
            continue

        b_bbox = BoundingBox(
            x1=round(b["bbox"][0], 2),
            y1=round(b["bbox"][1], 2),
            x2=round(b["bbox"][2], 2),
            y2=round(b["bbox"][3], 2),
        )

        in_table = False
        for t in tables:
            if t.bbox and b_bbox.iou(t.bbox) > 0.60:
                in_table = True
                break
            elif t.bbox and (
                b_bbox.x1 >= t.bbox.x1 - 2
                and b_bbox.y1 >= t.bbox.y1 - 2
                and b_bbox.x2 <= t.bbox.x2 + 2
                and b_bbox.y2 <= t.bbox.y2 + 2
            ):
                in_table = True
                break

        if in_table:
            continue

        assembled_lines: List[str] = []
        max_span_size = 0.0
        has_bold = False
        has_italic = False
        has_mono = False
        primary_font = None

        for line in lines:
            line_parts = []
            for span in line.get("spans", []):
                t = span.get("text", "")
                if not t:
                    continue
                size = float(span.get("size", 10.0))
                flags = int(span.get("flags", 0))
                font_name = span.get("font", "")

                if size > max_span_size:
                    max_span_size = size
                    primary_font = font_name

                if flags & 16 or "Bold" in font_name or "bold" in font_name:
                    has_bold = True
                if flags & 2 or "Italic" in font_name or "Oblique" in font_name:
                    has_italic = True
                if flags & 8 or "Courier" in font_name or "Mono" in font_name:
                    has_mono = True

                line_parts.append(t)

            line_str = "".join(line_parts).strip()
            if line_str:
                assembled_lines.append(line_str)

        if not assembled_lines:
            continue

        full_text_parts: List[str] = []
        for i, curr_line in enumerate(assembled_lines):
            if i == 0:
                full_text_parts.append(curr_line)
                continue

            prev_line = full_text_parts[-1]
            if (
                prev_line.endswith("-")
                and not prev_line.endswith(("--", " -"))
                and len(prev_line) > 1
                and prev_line[-2].isalpha()
                and curr_line[:1].isalpha()
            ):

                full_text_parts[-1] = f"{prev_line[:-1].rstrip()}{curr_line}"
            else:
                full_text_parts.append(f" {curr_line}")

        block_text = "".join(full_text_parts).strip()
        if not block_text:
            continue

        b_type = "paragraph"
        extra: Dict[str, Any] = {}

        if _is_math_formula(block_text):
            b_type = "formula"
            latex_clean = block_text.strip("$").strip()
            f_obj = PDFFormula(
                formula_id=f"form_p{page_num}_{formula_idx}",
                page_number=page_num,
                latex=latex_clean,
                display=not (block_text.startswith("$") and not block_text.startswith("$$")),
                bbox=b_bbox,
                source_method="native",
            )
            formulas.append(f_obj)
            formula_idx += 1

        elif max_span_size >= (body_size * 1.35) and (has_bold or max_span_size >= body_size * 1.5):
            b_type = "heading"
            extra["level"] = 1
        elif max_span_size >= (body_size * 1.20):
            b_type = "heading"
            extra["level"] = 2
        elif (max_span_size >= (body_size * 1.08) and has_bold) or (
            has_bold and len(block_text) < 70 and not block_text.endswith(".")
        ):
            b_type = "heading"
            extra["level"] = 3

        elif re.match(r"^(\d+[\.\)]|[-•*])\s+", block_text):
            b_type = "list"
            is_ordered = bool(re.match(r"^\d+[\.\)]\s+", block_text))
            extra["ordered"] = is_ordered
            extra["items"] = [block_text]

        elif has_mono and len(assembled_lines) > 1:
            b_type = "code"

        pdf_block = PDFBlock(
            block_id=f"blk_p{page_num}_{block_idx}",
            type=b_type,
            text=block_text,
            bbox=b_bbox,
            source_method="native",
            confidence=1.0,
            page_number=page_num,
            font_name=primary_font,
            font_size=max_span_size if max_span_size > 0 else body_size,
            is_bold=has_bold,
            is_italic=has_italic,
            reading_order=block_idx,
            extra=extra,
        )
        blocks.append(pdf_block)
        block_idx += 1

    for t in tables:
        t_block = PDFBlock(
            block_id=f"blk_p{page_num}_{t.table_id}",
            type="table",
            text="",
            bbox=t.bbox,
            source_method=t.source_method,
            confidence=t.confidence,
            page_number=page_num,
            reading_order=1,
            extra={
                "table_id": t.table_id,
                "headers": t.headers,
                "rows": t.rows,
                "caption": t.caption,
            },
        )
        blocks.append(t_block)

    ordered_blocks = sort_pdf_blocks_reading_order(blocks, page.rect.width)

    return ordered_blocks, tables, formulas, pdf_images

def extract_scanned_page(
    page: pymupdf.Page,
    page_num: int,
    ocr_engine: BaseOCREngine,
    dpi: int = 300,
    lang: str = "en",
    tier: str = "medium",
) -> Tuple[List[PDFBlock], List[PDFTable], List[PDFFormula], List[PDFImage]]:

    img = render_page_pixmap(page, dpi=dpi)
    raw_ocr_regions = ocr_engine.detect_and_recognize(img, lang=lang, tier=tier, mode="auto")

    ordered_regions = reconstruct_reading_order(raw_ocr_regions, page_width=img.width)
    merged_regions = reconstruct_paragraphs(ordered_regions)

    blocks: List[PDFBlock] = []
    formulas: List[PDFFormula] = []
    tables: List[PDFTable] = []
    images: List[PDFImage] = []

    block_idx = 1
    form_idx = 1

    for reg in merged_regions:
        pt_bbox = bbox_px_to_pdf_points(reg.bbox, dpi=dpi)

        if reg.type == "formula" or _is_math_formula(reg.text):
            f_clean = reg.text.strip("$").strip()
            form = PDFFormula(
                formula_id=f"form_p{page_num}_{form_idx}",
                page_number=page_num,
                latex=f_clean,
                display=True,
                bbox=pt_bbox,
                source_method="ocr",
                confidence=reg.confidence,
            )
            formulas.append(form)
            form_idx += 1

        b = PDFBlock(
            block_id=f"ocr_p{page_num}_{block_idx}",
            type=reg.type,
            text=reg.text,
            bbox=pt_bbox,
            source_method="ocr",
            confidence=reg.confidence,
            page_number=page_num,
            reading_order=reg.reading_order,
            extra=dict(reg.extra),
        )
        blocks.append(b)
        block_idx += 1

    return blocks, tables, formulas, images

def extract_hybrid_page(
    page: pymupdf.Page,
    page_num: int,
    ocr_engine: BaseOCREngine,
    dpi: int = 300,
    lang: str = "en",
    tier: str = "medium",
) -> Tuple[List[PDFBlock], List[PDFTable], List[PDFFormula], List[PDFImage]]:

    native_blocks, tables, formulas, pdf_images = extract_native_page(page, page_num)
    images_meta = extract_page_images(page)

    ocr_added_blocks: List[PDFBlock] = []
    hybrid_block_idx = len(native_blocks) + 1

    for img_dict in images_meta:
        raw_bytes = img_dict.get("bytes")
        if not raw_bytes or len(raw_bytes) < 100:
            continue

        try:
            pil_img = Image.open(io.BytesIO(raw_bytes))
            if pil_img.width < 50 or pil_img.height < 50:
                continue

            ocr_regions = ocr_engine.detect_and_recognize(pil_img, lang=lang, tier=tier, mode="auto")
            if not ocr_regions:
                continue

            img_bbox = img_dict["bbox"]
            scale_x = img_bbox.width / float(pil_img.width) if pil_img.width > 0 else 1.0
            scale_y = img_bbox.height / float(pil_img.height) if pil_img.height > 0 else 1.0

            for r in ocr_regions:

                pt_x1 = img_bbox.x1 + (r.bbox.x1 * scale_x)
                pt_y1 = img_bbox.y1 + (r.bbox.y1 * scale_y)
                pt_x2 = img_bbox.x1 + (r.bbox.x2 * scale_x)
                pt_y2 = img_bbox.y1 + (r.bbox.y2 * scale_y)
                mapped_bbox = BoundingBox(pt_x1, pt_y1, pt_x2, pt_y2)

                is_duplicate = False
                for nb in native_blocks:
                    if nb.bbox and mapped_bbox.iou(nb.bbox) > 0.35:
                        is_duplicate = True
                        break

                if not is_duplicate and r.text.strip():
                    ocr_added_blocks.append(
                        PDFBlock(
                            block_id=f"hyb_p{page_num}_{hybrid_block_idx}",
                            type=r.type,
                            text=r.text,
                            bbox=mapped_bbox,
                            source_method="ocr",
                            confidence=r.confidence,
                            page_number=page_num,
                            reading_order=hybrid_block_idx,
                            extra=dict(r.extra),
                        )
                    )
                    hybrid_block_idx += 1

        except Exception:
            continue

    combined_blocks = native_blocks + ocr_added_blocks

    ordered_blocks = sort_pdf_blocks_reading_order(combined_blocks, page.rect.width)

    return ordered_blocks, tables, formulas, pdf_images

def extract_page(
    page: pymupdf.Page,
    page_num: int,
    mode: str = "auto",
    ocr_engine: Optional[BaseOCREngine] = None,
    dpi: int = 300,
    lang: str = "en",
    tier: str = "medium",
) -> PDFPage:

    classification, reasons = classify_pdf_page(page)
    effective_mode = mode.lower().strip()

    extraction_methods: List[str] = []
    warnings: List[str] = []

    engine = ocr_engine
    if effective_mode in ("ocr", "force-ocr", "hybrid") or (
        effective_mode == "auto" and classification in ("scanned", "hybrid", "poor_text")
    ):
        if engine is None:
            engine = get_ocr_engine(engine_name="auto", tier=tier, lang=lang)

    if effective_mode in ("ocr", "force-ocr"):
        extraction_methods.append("ocr")
        blocks, tables, formulas, images = extract_scanned_page(
            page, page_num, engine, dpi=dpi, lang=lang, tier=tier
        )
    elif effective_mode == "hybrid":
        extraction_methods.extend(["native", "ocr"])
        blocks, tables, formulas, images = extract_hybrid_page(
            page, page_num, engine, dpi=dpi, lang=lang, tier=tier
        )
    elif effective_mode == "native":
        extraction_methods.append("native")
        blocks, tables, formulas, images = extract_native_page(page, page_num)
    else:

        if classification == "blank":
            extraction_methods.append("blank_detected")
            blocks, tables, formulas, images = [], [], [], []
        elif classification == "scanned":
            extraction_methods.append("ocr")
            blocks, tables, formulas, images = extract_scanned_page(
                page, page_num, engine, dpi=dpi, lang=lang, tier=tier
            )
        elif classification == "poor_text":
            extraction_methods.extend(["poor_text_fallback", "ocr"])
            warnings.append(
                f"Page {page_num} contains corrupted font encodings; fell back to OCR extraction."
            )
            blocks, tables, formulas, images = extract_scanned_page(
                page, page_num, engine, dpi=dpi, lang=lang, tier=tier
            )
        elif classification == "hybrid":
            extraction_methods.extend(["native", "ocr"])
            blocks, tables, formulas, images = extract_hybrid_page(
                page, page_num, engine, dpi=dpi, lang=lang, tier=tier
            )
        else:

            extraction_methods.append("native")
            blocks, tables, formulas, images = extract_native_page(page, page_num)

    page_links: List[Dict[str, Any]] = []
    try:
        for lk in page.get_links():
            uri = lk.get("uri")
            if uri:
                rect = lk.get("from")
                bbox = (
                    BoundingBox(round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2))
                    if rect
                    else None
                )
                page_links.append({
                    "href": uri,
                    "page_number": page_num,
                    "bbox": bbox.to_list() if bbox else None,
                })
    except Exception:
        pass

    pdf_page = PDFPage(
        page_number=page_num,
        width_pt=round(page.rect.width, 2),
        height_pt=round(page.rect.height, 2),
        rotation=page.rotation,
        classification=classification,
        classification_reasons=reasons,
        extraction_methods=extraction_methods,
        blocks=blocks,
        tables=tables,
        formulas=formulas,
        images=images,
        links=page_links,
        warnings=warnings,
    )
    pdf_page.update_stats()
    return pdf_page
