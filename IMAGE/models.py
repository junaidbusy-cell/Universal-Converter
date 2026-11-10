
from dataclasses import dataclass, field
from pathlib import Path
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
    LinkBlock,
    CodeBlock,
    MathBlock,
    BlockquoteBlock,
    _safe_serialize,
)

@dataclass
class BoundingBox:

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2.0

    def to_list(self) -> List[float]:
        return [round(self.x1, 2), round(self.y1, 2), round(self.x2, 2), round(self.y2, 2)]

    def to_dict(self) -> Dict[str, float]:
        return {
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2),
            "x2": round(self.x2, 2),
            "y2": round(self.y2, 2),
        }

    @classmethod
    def from_list(cls, coords: List[Union[int, float]]) -> "BoundingBox":
        if len(coords) < 4:
            raise ValueError(f"Expected 4 coordinates for BoundingBox, got {len(coords)}")
        return cls(float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))

    @classmethod
    def from_polygon(cls, pts: List[List[Union[int, float]]]) -> "BoundingBox":
        if not pts:
            return cls(0.0, 0.0, 0.0, 0.0)
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        return cls(min(xs), min(ys), max(xs), max(ys))

    def scale(self, scale_x: float, scale_y: float) -> "BoundingBox":
        return BoundingBox(
            x1=self.x1 * scale_x,
            y1=self.y1 * scale_y,
            x2=self.x2 * scale_x,
            y2=self.y2 * scale_y,
        )

    def iou(self, other: "BoundingBox") -> float:

        ix1 = max(self.x1, other.x1)
        iy1 = max(self.y1, other.y1)
        ix2 = min(self.x2, other.x2)
        iy2 = min(self.y2, other.y2)

        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        intersection = iw * ih

        if intersection <= 0.0:
            return 0.0

        union = self.area + other.area - intersection
        return intersection / union if union > 0.0 else 0.0

@dataclass
class OCRRegion:

    region_id: str
    type: str
    text: str
    bbox: BoundingBox
    polygon: List[List[float]] = field(default_factory=list)
    confidence: float = 1.0
    reading_order: int = 1
    line_number: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region_id": self.region_id,
            "type": self.type,
            "text": self.text,
            "bbox": self.bbox.to_list(),
            "polygon": [[round(x, 2), round(y, 2)] for x, y in self.polygon] if self.polygon else [],
            "confidence": round(self.confidence, 4),
            "reading_order": self.reading_order,
            "line_number": self.line_number,
            "extra": _safe_serialize(self.extra),
        }

@dataclass
class OCRTable:

    table_id: str
    bbox: BoundingBox
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    confidence: float = 1.0
    cells: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "bbox": self.bbox.to_list(),
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
            "confidence": round(self.confidence, 4),
            "cells": _safe_serialize(self.cells) if self.cells else [],
        }

@dataclass
class OCRFormula:

    formula_id: str
    bbox: BoundingBox
    latex: str
    display: bool = True
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "bbox": self.bbox.to_list(),
            "latex": self.latex,
            "display": self.display,
            "confidence": round(self.confidence, 4) if self.confidence is not None else None,
        }

@dataclass
class OCRPage:

    page_number: int
    width: int
    height: int
    orientation: int = 0
    transforms: Dict[str, Any] = field(default_factory=dict)
    regions: List[OCRRegion] = field(default_factory=list)
    tables: List[OCRTable] = field(default_factory=list)
    formulas: List[OCRFormula] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def sort_regions_by_reading_order(self) -> None:
        self.regions.sort(key=lambda r: (r.reading_order, r.bbox.y1, r.bbox.x1))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "transforms": dict(self.transforms),
            "regions": [r.to_dict() for r in self.regions],
            "tables": [t.to_dict() for t in self.tables],
            "formulas": [f.to_dict() for f in self.formulas],
            "images": [dict(img) for img in self.images],
            "warnings": list(self.warnings),
        }

@dataclass
class ImageOCRDocument:

    source: str
    source_type: str = "image"
    metadata: Dict[str, Any] = field(default_factory=dict)
    ocr_info: Dict[str, Any] = field(default_factory=dict)
    pages: List[OCRPage] = field(default_factory=list)
    text: str = ""
    markdown: str = ""
    chunks: List[Any] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_warning(self, msg: str) -> None:
        if msg and msg not in self.warnings:
            self.warnings.append(msg)

    def update_stats(self) -> None:

        page_count = len(self.pages)
        region_count = sum(len(p.regions) for p in self.pages)
        table_count = sum(len(p.tables) for p in self.pages)
        formula_count = sum(len(p.formulas) for p in self.pages)

        total_words = 0
        total_chars = 0
        low_confidence_count = 0

        for page in self.pages:
            for r in page.regions:
                total_chars += len(r.text)
                total_words += len(r.text.split())
                if r.confidence < 0.60:
                    low_confidence_count += 1

        self.stats.update({
            "page_count": page_count,
            "region_count": region_count,
            "table_count": table_count,
            "formula_count": formula_count,
            "word_count": total_words,
            "character_count": total_chars,
            "low_confidence_region_count": low_confidence_count,
            "warning_count": len(self.warnings),
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source": self.source,
            "source_type": self.source_type,
            "metadata": dict(self.metadata),
            "ocr": dict(self.ocr_info),
            "text": self.text,
            "markdown": self.markdown,
            "pages": [p.to_dict() for p in self.pages],
            "chunks": [_safe_serialize(c) for c in self.chunks],
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }

    def to_document(self) -> Document:

        doc = Document(
            schema_version="1.0",
            source=self.source,
            source_type="image",
            title=Path(self.source).stem.replace("_", " ").title(),
        )

        doc.metadata = Metadata(
            title=doc.title,
            extra={
                "image_metadata": dict(self.metadata),
                "ocr": dict(self.ocr_info),
            },
        )

        multi_page = len(self.pages) > 1

        for page in self.pages:
            if multi_page:
                doc.blocks.append(HeadingBlock(level=2, text=f"Page {page.page_number}"))

            sorted_regions = sorted(page.regions, key=lambda r: (r.reading_order, r.bbox.y1, r.bbox.x1))

            for region in sorted_regions:
                reg_type = region.type.lower()
                extra_payload = {
                    "bbox": region.bbox.to_list(),
                    "confidence": region.confidence,
                    "page_number": page.page_number,
                    "reading_order": region.reading_order,
                }

                if reg_type == "heading":
                    lvl = region.extra.get("level", 2)
                    doc.blocks.append(HeadingBlock(level=lvl, text=region.text, extra=extra_payload))
                elif reg_type == "code":
                    doc.blocks.append(CodeBlock(code=region.text, extra=extra_payload))
                elif reg_type == "list":
                    doc.blocks.append(ListBlock(items=[region.text], extra=extra_payload))
                elif reg_type == "quote":
                    doc.blocks.append(BlockquoteBlock(text=region.text, extra=extra_payload))
                elif reg_type == "formula":
                    doc.blocks.append(MathBlock(latex=region.text, math_type="display", extra=extra_payload))
                else:
                    doc.blocks.append(ParagraphBlock(text=region.text, extra=extra_payload))

            for tbl in page.tables:
                doc.blocks.append(
                    TableBlock(
                        headers=tbl.headers,
                        rows=tbl.rows,
                        extra={"bbox": tbl.bbox.to_list(), "page_number": page.page_number},
                    )
                )
                doc.tables.append(tbl.to_dict())

            for form in page.formulas:
                doc.blocks.append(
                    MathBlock(
                        latex=form.latex,
                        math_type="display" if form.display else "inline",
                        extra={"bbox": form.bbox.to_list(), "page_number": page.page_number},
                    )
                )

        doc.warnings.extend(self.warnings)
        doc.update_stats()
        return doc
