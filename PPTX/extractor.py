
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pptx
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.shapes.autoshape import Shape
from pptx.shapes.picture import Picture
from pptx.shapes.group import GroupShape

from common.models import Metadata
from .models import ElementPosition, SlideElement, SlideModel, PresentationModel
from .parser import extract_presentation_metadata
from .assets import PPTXAssetManager

def _clean_table_cell(text: str) -> str:

    if not text:
        return ""

    s = text.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")

    return s.replace("|", "\\|").strip()

def _get_shape_position(shape: Any) -> Optional[ElementPosition]:

    try:
        left = int(getattr(shape, "left", 0) or 0)
        top = int(getattr(shape, "top", 0) or 0)
        width = int(getattr(shape, "width", 0) or 0)
        height = int(getattr(shape, "height", 0) or 0)
        return ElementPosition(left_emu=left, top_emu=top, width_emu=width, height_emu=height)
    except Exception:
        return None

def _extract_text_frame(text_frame: Any) -> Tuple[str, List[Dict[str, Any]]]:

    paragraphs_data: List[Dict[str, Any]] = []
    full_text_parts: List[str] = []

    for p in getattr(text_frame, "paragraphs", []):
        p_text = getattr(p, "text", "") or ""
        p_level = getattr(p, "level", 0) or 0

        runs_data: List[Dict[str, Any]] = []
        for run in getattr(p, "runs", []):
            r_text = getattr(run, "text", "") or ""
            if not r_text:
                continue

            font = getattr(run, "font", None)
            bold = getattr(font, "bold", None) if font else None
            italic = getattr(font, "italic", None) if font else None
            underline = getattr(font, "underline", None) if font else None
            size_pt = font.size.pt if (font and font.size) else None
            font_name = font.name if font else None

            color_rgb = None
            if font and getattr(font, "color", None) and getattr(font.color, "rgb", None):
                try:
                    color_rgb = str(font.color.rgb)
                except Exception:
                    pass

            hyperlink = None
            hlink = getattr(run, "hyperlink", None)
            if hlink and getattr(hlink, "address", None):
                hyperlink = hlink.address

            runs_data.append({
                "text": r_text,
                "bold": bool(bold),
                "italic": bool(italic),
                "underline": bool(underline),
                "size_pt": size_pt,
                "font_name": font_name,
                "color": color_rgb,
                "hyperlink": hyperlink,
            })

        paragraphs_data.append({
            "text": p_text,
            "level": p_level,
            "is_bullet": p_level > 0,
            "runs": runs_data,
        })
        if p_text.strip():
            full_text_parts.append(p_text.strip())

    combined_text = "\n".join(full_text_parts)
    return combined_text, paragraphs_data

def _extract_table(shape: Any) -> Tuple[List[str], List[List[str]], int, int, List[Dict[str, Any]]]:

    table = shape.table
    row_count = len(table.rows)
    col_count = len(table.columns)

    matrix: List[List[str]] = []
    merged_cells: List[Dict[str, Any]] = []

    for r_idx, row in enumerate(table.rows):
        row_vals: List[str] = []
        for c_idx, cell in enumerate(row.cells):
            cell_text = cell.text_frame.text if cell.text_frame else ""
            cleaned = _clean_table_cell(cell_text)
            row_vals.append(cleaned)

            is_origin = getattr(cell, "is_merge_origin", False)
            is_spanned = getattr(cell, "is_spanned", False)
            if is_origin or is_spanned:
                merged_cells.append({
                    "row": r_idx,
                    "col": c_idx,
                    "is_origin": is_origin,
                    "is_spanned": is_spanned,
                    "span_height": getattr(cell, "span_height", 1),
                    "span_width": getattr(cell, "span_width", 1),
                })
        matrix.append(row_vals)

    headers = matrix[0] if matrix else []
    data_rows = matrix[1:] if len(matrix) > 1 else []
    return headers, data_rows, row_count, col_count, merged_cells

def _extract_chart(shape: Any) -> Tuple[Optional[str], Optional[str], List[str], List[Dict[str, Any]]]:

    chart = shape.chart
    chart_type_name = getattr(chart.chart_type, "name", str(chart.chart_type))

    chart_title = None
    if getattr(chart, "has_title", False) and chart.chart_title:
        tf = getattr(chart.chart_title, "text_frame", None)
        if tf and tf.text:
            chart_title = tf.text.strip()

    categories: List[str] = []
    if getattr(chart, "plots", None) and len(chart.plots) > 0:
        try:
            categories = [str(c) for c in chart.plots[0].categories]
        except Exception:
            pass

    series_list: List[Dict[str, Any]] = []
    for s in getattr(chart, "series", []):
        s_name = getattr(s, "name", "") or f"Series_{len(series_list) + 1}"
        s_values: List[Any] = []
        for val in getattr(s, "values", []):
            if val is not None and isinstance(val, (int, float)):
                if math.isnan(val):
                    s_values.append(None)
                else:
                    s_values.append(val)
            else:
                s_values.append(val)
        series_list.append({"name": str(s_name), "values": s_values})

    return chart_type_name, chart_title, categories, series_list

def extract_shape(
    shape: Any,
    slide_number: int,
    shape_order: int,
    asset_mgr: Optional[PPTXAssetManager] = None,
) -> Optional[SlideElement]:

    elem_id = f"shape_{getattr(shape, 'shape_id', shape_order)}"
    elem_name = getattr(shape, "name", f"Shape_{shape_order}") or f"Shape_{shape_order}"
    pos = _get_shape_position(shape)

    if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.GROUP:
        children: List[SlideElement] = []
        for c_idx, child in enumerate(getattr(shape, "shapes", []), start=1):
            child_elem = extract_shape(child, slide_number, c_idx, asset_mgr=asset_mgr)
            if child_elem:
                children.append(child_elem)
        return SlideElement(
            element_id=elem_id,
            element_name=elem_name,
            type="group",
            shape_order=shape_order,
            position=pos,
            children=children,
        )

    if getattr(shape, "has_table", False):
        headers, rows, r_cnt, c_cnt, merged = _extract_table(shape)
        return SlideElement(
            element_id=elem_id,
            element_name=elem_name,
            type="table",
            shape_order=shape_order,
            position=pos,
            headers=headers,
            rows=rows,
            row_count=r_cnt,
            column_count=c_cnt,
            merged_cells=merged,
        )

    if getattr(shape, "has_chart", False):
        c_type, c_title, categories, series = _extract_chart(shape)
        return SlideElement(
            element_id=elem_id,
            element_name=elem_name,
            type="chart",
            shape_order=shape_order,
            position=pos,
            chart_type=c_type,
            chart_title=c_title,
            categories=categories,
            series=series,
        )

    if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE or hasattr(shape, "image"):
        img_dict = asset_mgr.extract_image(shape, slide_number, alt_text=elem_name) if asset_mgr else None
        img_path = img_dict.get("path") if img_dict else None
        img_format = img_dict.get("format") if img_dict else None
        img_size = img_dict.get("size_bytes") if img_dict else None
        img_sha = img_dict.get("sha256") if img_dict else None

        return SlideElement(
            element_id=elem_id,
            element_name=elem_name,
            type="image",
            shape_order=shape_order,
            position=pos,
            image_path=img_path,
            alt_text=elem_name,
            format=img_format,
            size_bytes=img_size,
            sha256=img_sha,
        )

    if getattr(shape, "has_text_frame", False):
        text, paragraphs = _extract_text_frame(shape.text_frame)
        is_placeholder = getattr(shape, "is_placeholder", False)
        ph_type_name = None
        elem_type = "text_box"

        if is_placeholder:
            try:
                ph_type = shape.placeholder_format.type
                ph_type_name = getattr(ph_type, "name", str(ph_type))
                if ph_type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE):
                    elem_type = "title"
            except Exception:
                pass

        return SlideElement(
            element_id=elem_id,
            element_name=elem_name,
            type=elem_type,
            shape_order=shape_order,
            position=pos,
            text=text,
            paragraphs=paragraphs,
            is_placeholder=is_placeholder,
            placeholder_type=ph_type_name,
        )

    return SlideElement(
        element_id=elem_id,
        element_name=elem_name,
        type="shape",
        shape_order=shape_order,
        position=pos,
    )

def compute_reading_order(elements: List[SlideElement]) -> List[SlideElement]:

    def sort_key(elem: SlideElement):
        p_type = elem.placeholder_type or ""
        if p_type in ("TITLE", "CENTER_TITLE") or elem.type == "title":
            priority = 0
        elif p_type == "SUBTITLE":
            priority = 1
        else:
            priority = 2

        top = elem.position.top_emu if elem.position else 0
        left = elem.position.left_emu if elem.position else 0

        top_band = top // 100000

        return (priority, top_band, left, elem.shape_order)

    sorted_elems = sorted(elements, key=sort_key)
    for idx, elem in enumerate(sorted_elems, start=1):
        elem.reading_order = idx

    return elements

def extract_slide(
    slide: Any,
    slide_number: int,
    asset_mgr: Optional[PPTXAssetManager] = None,
) -> SlideModel:

    slide_id = getattr(slide, "slide_id", slide_number)
    is_hidden = (getattr(slide.element, "get", lambda k: None)("show") == "0")
    visibility = "hidden" if is_hidden else "visible"

    layout_name = "Blank"
    try:
        if getattr(slide, "slide_layout", None):
            layout_name = getattr(slide.slide_layout, "name", "Layout")
    except Exception:
        pass

    elements: List[SlideElement] = []
    slide_title = ""

    for s_idx, shape in enumerate(getattr(slide, "shapes", []), start=1):
        elem = extract_shape(shape, slide_number, s_idx, asset_mgr=asset_mgr)
        if elem:
            elements.append(elem)

    compute_reading_order(elements)

    for e in elements:
        if e.type == "title" or (e.is_placeholder and e.placeholder_type in ("TITLE", "CENTER_TITLE")):
            if e.text.strip():
                slide_title = e.text.strip()
                break

    if not slide_title:
        for e in sorted(elements, key=lambda x: x.reading_order):
            if e.type in ("text_box", "title") and e.text.strip():
                first_line = e.text.strip().splitlines()[0]
                if len(first_line) < 120:
                    slide_title = first_line
                    break

    notes_text: Optional[str] = None
    notes_paragraphs: List[str] = []

    if getattr(slide, "has_notes_slide", False):
        try:
            notes_slide = slide.notes_slide
            tf = getattr(notes_slide, "notes_text_frame", None)
            if tf and tf.text:
                notes_text = tf.text.strip()
                notes_paragraphs = [p.text.strip() for p in tf.paragraphs if p.text and p.text.strip()]
        except Exception:
            pass

    return SlideModel(
        slide_number=slide_number,
        slide_id=slide_id,
        title=slide_title,
        layout=layout_name,
        visibility=visibility,
        is_visible=(not is_hidden),
        elements=elements,
        notes=notes_text,
        notes_paragraphs=notes_paragraphs,
    )

def extract_presentation(
    prs: pptx.Presentation,
    source_path: Union[str, Path],
    asset_mgr: Optional[PPTXAssetManager] = None,
) -> PresentationModel:

    src_str = str(source_path)
    stem = Path(source_path).stem

    meta = extract_presentation_metadata(prs)
    title = meta.title or stem.replace("_", " ").title()
    dimensions = meta.extra.get("dimensions", {})

    slides: List[SlideModel] = []
    for idx, slide in enumerate(getattr(prs, "slides", []), start=1):
        s_model = extract_slide(slide, slide_number=idx, asset_mgr=asset_mgr)
        slides.append(s_model)

    media_records: List[Dict[str, Any]] = []
    if asset_mgr:
        for sha, (rel_path, m_dict) in asset_mgr._hash_cache.items():
            media_records.append(dict(m_dict))

    prs_model = PresentationModel(
        source=src_str,
        title=title,
        metadata=meta,
        dimensions=dimensions,
        slides=slides,
        media=media_records,
    )
    prs_model.update_stats()
    return prs_model
