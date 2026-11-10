
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union

from common.models import (
    Document,
    Metadata,
    Block,
    HeadingBlock,
    ParagraphBlock,
    ListBlock,
    TableBlock,
    ImageBlock,
    BlockquoteBlock,
    EmbedBlock,
    _safe_serialize,
)

EMUS_PER_INCH = 914400
DPI = 96
EMUS_PER_PIXEL = EMUS_PER_INCH / DPI

@dataclass
class ElementPosition:

    left_emu: int = 0
    top_emu: int = 0
    width_emu: int = 0
    height_emu: int = 0

    @property
    def left_in(self) -> float:
        return round(self.left_emu / EMUS_PER_INCH, 2)

    @property
    def top_in(self) -> float:
        return round(self.top_emu / EMUS_PER_INCH, 2)

    @property
    def width_in(self) -> float:
        return round(self.width_emu / EMUS_PER_INCH, 2)

    @property
    def height_in(self) -> float:
        return round(self.height_emu / EMUS_PER_INCH, 2)

    @property
    def left_px(self) -> int:
        return round(self.left_emu / EMUS_PER_PIXEL)

    @property
    def top_px(self) -> int:
        return round(self.top_emu / EMUS_PER_PIXEL)

    @property
    def width_px(self) -> int:
        return round(self.width_emu / EMUS_PER_PIXEL)

    @property
    def height_px(self) -> int:
        return round(self.height_emu / EMUS_PER_PIXEL)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "left_emu": self.left_emu,
            "top_emu": self.top_emu,
            "width_emu": self.width_emu,
            "height_emu": self.height_emu,
            "left_px": self.left_px,
            "top_px": self.top_px,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "left_in": self.left_in,
            "top_in": self.top_in,
            "width_in": self.width_in,
            "height_in": self.height_in,
        }

@dataclass
class SlideElement:

    element_id: str
    element_name: str
    type: str
    shape_order: int = 0
    reading_order: int = 0
    position: Optional[ElementPosition] = None

    text: str = ""
    paragraphs: List[Dict[str, Any]] = field(default_factory=list)
    is_placeholder: bool = False
    placeholder_type: Optional[str] = None

    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    row_count: int = 0
    column_count: int = 0
    merged_cells: List[Dict[str, Any]] = field(default_factory=list)

    image_path: Optional[str] = None
    alt_text: str = ""
    format: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None

    chart_type: Optional[str] = None
    chart_title: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    series: List[Dict[str, Any]] = field(default_factory=list)

    children: List["SlideElement"] = field(default_factory=list)

    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "element_id": self.element_id,
            "element_name": self.element_name,
            "type": self.type,
            "shape_order": self.shape_order,
            "reading_order": self.reading_order,
        }
        if self.position:
            d["position"] = self.position.to_dict()

        if self.type in ("text_box", "title", "shape"):
            d["text"] = self.text
            d["paragraphs"] = _safe_serialize(self.paragraphs)
            if self.is_placeholder:
                d["is_placeholder"] = True
                d["placeholder_type"] = self.placeholder_type

        elif self.type == "table":
            d["table"] = {
                "headers": list(self.headers),
                "rows": _safe_serialize(self.rows),
                "row_count": self.row_count,
                "column_count": self.column_count,
                "merged_cells": _safe_serialize(self.merged_cells),
            }

        elif self.type == "image":
            d["image"] = {
                "path": self.image_path,
                "alt_text": self.alt_text,
                "format": self.format,
                "size_bytes": self.size_bytes,
                "sha256": self.sha256,
            }

        elif self.type == "chart":
            d["chart"] = {
                "type": self.chart_type,
                "title": self.chart_title,
                "categories": list(self.categories),
                "series": _safe_serialize(self.series),
            }

        elif self.type == "group":
            d["children"] = [c.to_dict() for c in self.children]

        if self.extra:
            d["extra"] = _safe_serialize(self.extra)
        return d

@dataclass
class SlideModel:

    slide_number: int
    slide_id: int
    title: str = ""
    layout: str = "Blank"
    visibility: str = "visible"
    is_visible: bool = True
    elements: List[SlideElement] = field(default_factory=list)
    notes: Optional[str] = None
    notes_paragraphs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slide_number": self.slide_number,
            "slide_id": self.slide_id,
            "title": self.title,
            "layout": self.layout,
            "visibility": self.visibility,
            "is_visible": self.is_visible,
            "elements": [e.to_dict() for e in self.elements],
            "notes": self.notes,
            "notes_paragraphs": list(self.notes_paragraphs),
            "warnings": list(self.warnings),
        }

@dataclass
class PresentationModel:

    source: str = ""
    title: str = ""
    metadata: Metadata = field(default_factory=Metadata)
    dimensions: Dict[str, Any] = field(default_factory=dict)
    slides: List[SlideModel] = field(default_factory=list)
    media: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def update_stats(self) -> None:

        total_elements = sum(len(s.elements) for s in self.slides)
        total_tables = sum(sum(1 for e in s.elements if e.type == "table") for s in self.slides)
        total_charts = sum(sum(1 for e in s.elements if e.type == "chart") for s in self.slides)
        total_images = sum(sum(1 for e in s.elements if e.type == "image") for s in self.slides)
        visible_slides = sum(1 for s in self.slides if s.is_visible)

        self.stats.update({
            "slide_count": len(self.slides),
            "visible_slide_count": visible_slides,
            "hidden_slide_count": len(self.slides) - visible_slides,
            "total_element_count": total_elements,
            "total_table_count": total_tables,
            "total_chart_count": total_charts,
            "total_image_count": total_images,
            "media_count": len(self.media),
            "warning_count": len(self.warnings),
        })

    def to_dict(self) -> Dict[str, Any]:

        return {
            "source": self.source,
            "title": self.title,
            "metadata": self.metadata.to_dict(),
            "dimensions": dict(self.dimensions),
            "slides": [s.to_dict() for s in self.slides],
            "media": _safe_serialize(self.media),
            "stats": dict(self.stats),
            "warnings": list(self.warnings),
        }

    def to_document(self, include_hidden_slides: bool = True, include_notes: bool = True) -> Document:

        self.update_stats()
        doc = Document(
            schema_version="1.0",
            source=self.source,
            source_type="pptx",
            title=self.title or self.metadata.title or "Presentation",
            metadata=self.metadata,
        )

        doc.metadata.extra["presentation"] = self.to_dict()
        doc.metadata.extra["slide_count"] = len(self.slides)

        for w in self.warnings:
            doc.add_warning(w)

        for s in self.slides:
            if not s.is_visible and not include_hidden_slides:
                continue

            for w in s.warnings:
                doc.add_warning(f"[Slide {s.slide_number}] {w}")

            vis_suffix = "" if s.is_visible else " (Hidden)"
            slide_heading_text = f"Slide {s.slide_number}: {s.title or 'Untitled'}{vis_suffix}"
            doc.blocks.append(HeadingBlock(level=2, text=slide_heading_text))

            def collect_blocks(elements: List[SlideElement]):

                sorted_elems = sorted(elements, key=lambda e: (e.reading_order, e.shape_order))
                for elem in sorted_elems:
                    if elem.type in ("text_box", "title", "shape"):

                        has_bullets = any(p.get("level", 0) > 0 or p.get("is_bullet", False) for p in elem.paragraphs)
                        if has_bullets and elem.paragraphs:
                            bullet_items = []
                            for p in elem.paragraphs:
                                p_text = p.get("text", "").strip()
                                if p_text:
                                    bullet_items.append(p_text)
                            if bullet_items:
                                doc.blocks.append(ListBlock(ordered=False, items=bullet_items))
                        else:
                            if elem.text.strip():

                                if elem.placeholder_type in ("SUBTITLE", "CENTER_TITLE") and elem.text != s.title:
                                    doc.blocks.append(HeadingBlock(level=3, text=elem.text.strip()))
                                else:
                                    doc.blocks.append(ParagraphBlock(text=elem.text.strip()))

                    elif elem.type == "table":
                        doc.blocks.append(TableBlock(
                            headers=list(elem.headers),
                            rows=[[str(c) for c in r] for r in elem.rows],
                            caption=f"Slide {s.slide_number} Table",
                        ))
                        doc.tables.append({
                            "slide": s.slide_number,
                            "name": elem.element_name,
                            "headers": list(elem.headers),
                            "rows": elem.rows,
                        })

                    elif elem.type == "chart":

                        chart_headers = ["Category"] + [ser["name"] for ser in elem.series]
                        chart_rows: List[List[str]] = []
                        for idx, cat in enumerate(elem.categories):
                            row = [str(cat)]
                            for ser in elem.series:
                                vals = ser.get("values", [])
                                row.append(str(vals[idx]) if idx < len(vals) and vals[idx] is not None else "")
                            chart_rows.append(row)

                        chart_caption = f"Slide {s.slide_number} Chart: {elem.chart_title or elem.chart_type}"
                        if chart_rows:
                            doc.blocks.append(TableBlock(
                                headers=chart_headers,
                                rows=chart_rows,
                                caption=chart_caption,
                            ))
                        doc.blocks.append(EmbedBlock(
                            embed_type="chart",
                            title=chart_caption,
                            src=None,
                        ))

                    elif elem.type == "image":
                        img_path = elem.image_path or ""
                        doc.blocks.append(ImageBlock(
                            src=img_path,
                            alt=elem.alt_text or elem.element_name,
                            title=f"Slide {s.slide_number} - {elem.element_name}",
                        ))
                        doc.images.append({
                            "slide": s.slide_number,
                            "name": elem.element_name,
                            "path": img_path,
                            "alt_text": elem.alt_text,
                            "sha256": elem.sha256,
                        })

                    elif elem.type == "group":
                        collect_blocks(elem.children)

            collect_blocks(s.elements)

            if include_notes and s.notes and s.notes.strip():
                doc.blocks.append(BlockquoteBlock(
                    text=f"Speaker Notes:\n{s.notes.strip()}",
                    citation=None,
                ))

        doc.update_stats()
        return doc
