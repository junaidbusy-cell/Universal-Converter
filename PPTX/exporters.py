
import json
from typing import Any, Dict, List, Optional, Union
import yaml

from .models import PresentationModel, SlideModel, SlideElement
from common.models import Document, _safe_serialize
from common.exporters import export_markdown as common_export_md, export_text as common_export_txt

def _render_element_markdown(elem: SlideElement) -> List[str]:

    lines: List[str] = []

    if elem.type in ("text_box", "title", "shape"):

        has_bullets = any(p.get("level", 0) > 0 or p.get("is_bullet", False) for p in elem.paragraphs)
        if has_bullets and elem.paragraphs:
            for p in elem.paragraphs:
                p_text = p.get("text", "").strip()
                if not p_text:
                    continue
                indent = "  " * p.get("level", 0)
                lines.append(f"{indent}- {p_text}")
            lines.append("")
        else:
            if elem.text.strip():
                if elem.placeholder_type in ("SUBTITLE", "CENTER_TITLE"):
                    lines.append(f"### {elem.text.strip()}\n")
                else:
                    lines.append(f"{elem.text.strip()}\n")

    elif elem.type == "table":
        if elem.headers:
            clean_headers = [str(h).replace("|", "\\|").replace("\n", " ") for h in elem.headers]
            col_count = len(clean_headers)
            lines.append("| " + " | ".join(clean_headers) + " |")
            lines.append("| " + " | ".join(["---"] * col_count) + " |")
            for row in elem.rows:
                clean_row = [str(c).replace("|", "\\|").replace("\n", "<br>") for c in row]
                padded = clean_row + [""] * max(0, col_count - len(clean_row))
                lines.append("| " + " | ".join(padded[:col_count]) + " |")
            lines.append("")

    elif elem.type == "chart":
        title_str = elem.chart_title or elem.chart_type or "Chart"
        lines.append(f"### Chart: {title_str}\n")
        if elem.categories and elem.series:
            clean_headers = ["Category"] + [s["name"] for s in elem.series]
            col_count = len(clean_headers)
            lines.append("| " + " | ".join(clean_headers) + " |")
            lines.append("| " + " | ".join(["---"] * col_count) + " |")
            for idx, cat in enumerate(elem.categories):
                row_vals = [str(cat)]
                for ser in elem.series:
                    vals = ser.get("values", [])
                    row_vals.append(str(vals[idx]) if idx < len(vals) and vals[idx] is not None else "")
                lines.append("| " + " | ".join(row_vals[:col_count]) + " |")
            lines.append("")

    elif elem.type == "image":
        img_path = elem.image_path or ""
        alt_str = elem.alt_text or elem.element_name
        lines.append(f"![{alt_str}]({img_path})\n")

    elif elem.type == "group":
        sorted_children = sorted(elem.children, key=lambda c: (c.reading_order, c.shape_order))
        for child in sorted_children:
            lines.extend(_render_element_markdown(child))

    return lines

def export_markdown(
    target: Union[PresentationModel, Document],
    include_frontmatter: bool = True,
    include_hidden_slides: bool = False,
    include_notes: bool = True,
) -> str:

    if isinstance(target, Document):
        return common_export_md(target, include_frontmatter=include_frontmatter)

    prs: PresentationModel = target
    parts: List[str] = []

    if include_frontmatter:
        fm_data: Dict[str, Any] = {
            "source": prs.source,
            "source_type": "pptx",
            "title": prs.title or None,
            "slide_count": len(prs.slides),
        }
        if prs.metadata.author:
            fm_data["author"] = prs.metadata.author
        if prs.metadata.date:
            fm_data["date"] = prs.metadata.date
        if prs.dimensions:
            fm_data["aspect_ratio"] = prs.dimensions.get("aspect_ratio")

        fm_yaml = yaml.safe_dump(fm_data, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    parts.append(f"# {prs.title}\n")

    first_slide = True
    for slide in prs.slides:
        if not slide.is_visible and not include_hidden_slides:
            continue

        if not first_slide:
            parts.append("\n---\n")
        first_slide = False

        vis_suffix = "" if slide.is_visible else " *(Hidden)*"
        slide_title = slide.title or f"Slide {slide.slide_number}"
        parts.append(f"## Slide {slide.slide_number}: {slide_title}{vis_suffix}\n")

        sorted_elems = sorted(slide.elements, key=lambda e: (e.reading_order, e.shape_order))
        for elem in sorted_elems:

            if elem.type == "title" and elem.text.strip() == slide.title:
                continue
            elem_lines = _render_element_markdown(elem)
            if elem_lines:
                parts.append("\n".join(elem_lines).strip() + "\n")

        if include_notes and slide.notes and slide.notes.strip():
            parts.append("### Speaker Notes\n")
            parts.append(f"> {slide.notes.strip()}\n")

    return "\n".join(parts).strip() + "\n"

def export_text(
    target: Union[PresentationModel, Document],
    include_hidden_slides: bool = False,
    include_notes: bool = True,
) -> str:

    if isinstance(target, Document):
        return common_export_txt(target)

    prs: PresentationModel = target
    parts: List[str] = []

    banner = "=" * 80
    parts.append(banner)
    parts.append(f"PRESENTATION: {prs.title}")
    parts.append(banner)
    parts.append("")

    for slide in prs.slides:
        if not slide.is_visible and not include_hidden_slides:
            continue

        slide_sep = "-" * 80
        vis_suffix = "" if slide.is_visible else " [HIDDEN]"
        slide_title = slide.title or f"Slide {slide.slide_number}"
        parts.append(slide_sep)
        parts.append(f"SLIDE {slide.slide_number}: {slide_title}{vis_suffix}")
        parts.append(slide_sep)

        sorted_elems = sorted(slide.elements, key=lambda e: (e.reading_order, e.shape_order))

        def print_elem_txt(elem: SlideElement):
            if elem.type in ("text_box", "title", "shape"):
                if elem.text.strip() and elem.text.strip() != slide.title:
                    parts.append(elem.text.strip())
            elif elem.type == "table":
                parts.append(f"[Table: {elem.element_name}]")
                if elem.headers:
                    parts.append("\t".join(elem.headers))
                for row in elem.rows:
                    parts.append("\t".join(row))
            elif elem.type == "chart":
                title_str = elem.chart_title or elem.chart_type or "Chart"
                parts.append(f"[Chart: {title_str}]")
                if elem.categories and elem.series:
                    parts.append("\t".join(["Category"] + [s["name"] for s in elem.series]))
                    for idx, cat in enumerate(elem.categories):
                        row_vals = [str(cat)]
                        for ser in elem.series:
                            vals = ser.get("values", [])
                            row_vals.append(str(vals[idx]) if idx < len(vals) and vals[idx] is not None else "")
                        parts.append("\t".join(row_vals))
            elif elem.type == "image":
                parts.append(f"[Image: {elem.alt_text or elem.element_name} -> {elem.image_path}]")
            elif elem.type == "group":
                for child in sorted(elem.children, key=lambda c: (c.reading_order, c.shape_order)):
                    print_elem_txt(child)

        for elem in sorted_elems:
            print_elem_txt(elem)

        if include_notes and slide.notes and slide.notes.strip():
            parts.append("\nSpeaker Notes:")
            parts.append(f"  {slide.notes.strip()}")

        parts.append("")

    return "\n".join(parts).strip() + "\n"

def export_json(target: Union[PresentationModel, Document], indent: int = 2) -> str:

    if isinstance(target, Document):
        d = target.to_dict()
    else:
        d = target.to_dict()

    return json.dumps(d, indent=indent, ensure_ascii=False)
