
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
from IMAGE.models import BoundingBox

@dataclass
class PDFBlock:

    block_id: str
    type: str
    text: str
    bbox: Optional[BoundingBox] = None
    source_method: str = "native"
    confidence: float = 1.0
    page_number: int = 1
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    is_bold: bool = False
    is_italic: bool = False
    reading_order: int = 1
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id": self.block_id,
            "type": self.type,
            "text": self.text,
            "bbox": self.bbox.to_list() if self.bbox else None,
            "source_method": self.source_method,
            "confidence": round(self.confidence, 4),
            "page_number": self.page_number,
            "font_name": self.font_name,
            "font_size": round(self.font_size, 2) if self.font_size is not None else None,
            "is_bold": self.is_bold,
            "is_italic": self.is_italic,
            "reading_order": self.reading_order,
            "extra": _safe_serialize(self.extra),
        }

@dataclass
class PDFTable:

    table_id: str
    page_number: int
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    bbox: Optional[BoundingBox] = None
    caption: Optional[str] = None
    source_method: str = "native"
    confidence: float = 1.0
    cells: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "page_number": self.page_number,
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
            "bbox": self.bbox.to_list() if self.bbox else None,
            "caption": self.caption,
            "source_method": self.source_method,
            "confidence": round(self.confidence, 4),
            "cells": _safe_serialize(self.cells) if self.cells else [],
        }

@dataclass
class PDFFormula:

    formula_id: str
    page_number: int
    latex: str
    display: bool = True
    bbox: Optional[BoundingBox] = None
    source_method: str = "native"
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "page_number": self.page_number,
            "latex": self.latex,
            "display": self.display,
            "bbox": self.bbox.to_list() if self.bbox else None,
            "source_method": self.source_method,
            "confidence": round(self.confidence, 4),
        }

@dataclass
class PDFImage:

    image_id: str
    page_number: int
    bbox: Optional[BoundingBox] = None
    width_px: int = 0
    height_px: int = 0
    format: str = "png"
    source_path: Optional[str] = None
    ocr_applied: bool = False
    extracted_text: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_number": self.page_number,
            "bbox": self.bbox.to_list() if self.bbox else None,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "format": self.format,
            "source_path": self.source_path,
            "ocr_applied": self.ocr_applied,
            "extracted_text": self.extracted_text,
            "extra": _safe_serialize(self.extra),
        }

@dataclass
class PDFPage:

    page_number: int
    width_pt: float
    height_pt: float
    rotation: int = 0
    classification: str = "digital"
    classification_reasons: List[str] = field(default_factory=list)
    extraction_methods: List[str] = field(default_factory=list)
    blocks: List[PDFBlock] = field(default_factory=list)
    tables: List[PDFTable] = field(default_factory=list)
    formulas: List[PDFFormula] = field(default_factory=list)
    images: List[PDFImage] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def sort_blocks_by_reading_order(self) -> None:
        self.blocks.sort(key=lambda b: (
            b.reading_order,
            b.bbox.y1 if b.bbox else 0.0,
            b.bbox.x1 if b.bbox else 0.0
        ))

    def update_stats(self) -> None:
        text_len = sum(len(b.text) for b in self.blocks)
        self.stats = {
            "block_count": len(self.blocks),
            "table_count": len(self.tables),
            "formula_count": len(self.formulas),
            "image_count": len(self.images),
            "link_count": len(self.links),
            "character_count": text_len,
            "classification": self.classification,
            "extraction_methods": list(self.extraction_methods),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width_pt": round(self.width_pt, 2),
            "height_pt": round(self.height_pt, 2),
            "rotation": self.rotation,
            "classification": self.classification,
            "classification_reasons": list(self.classification_reasons),
            "extraction_methods": list(self.extraction_methods),
            "blocks": [b.to_dict() for b in self.blocks],
            "tables": [t.to_dict() for t in self.tables],
            "formulas": [f.to_dict() for f in self.formulas],
            "images": [img.to_dict() for img in self.images],
            "links": _safe_serialize(self.links),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }

@dataclass
class PDFDocument:

    source: str
    page_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    extraction_info: Dict[str, Any] = field(default_factory=dict)
    pages: List[PDFPage] = field(default_factory=list)
    text: str = ""
    markdown: str = ""
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def update_stats(self) -> None:
        total_blocks = sum(len(p.blocks) for p in self.pages)
        total_tables = sum(len(p.tables) for p in self.pages)
        total_formulas = sum(len(p.formulas) for p in self.pages)
        total_images = sum(len(p.images) for p in self.pages)
        classifications = [p.classification for p in self.pages]

        self.stats = {
            "page_count": len(self.pages),
            "character_count": len(self.text),
            "word_count": len(self.text.split()) if self.text else 0,
            "block_count": total_blocks,
            "table_count": total_tables,
            "formula_count": total_formulas,
            "image_count": total_images,
            "chunk_count": len(self.chunks),
            "warning_count": len(self.warnings),
            "page_classifications": classifications,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source": self.source,
            "source_type": "pdf",
            "page_count": self.page_count,
            "metadata": _safe_serialize(self.metadata),
            "extraction_info": _safe_serialize(self.extraction_info),
            "text": self.text,
            "markdown": self.markdown,
            "pages": [p.to_dict() for p in self.pages],
            "chunks": _safe_serialize(self.chunks),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }

    def to_document(self) -> Document:

        meta = Metadata(
            title=self.metadata.get("title") or Path(self.source).stem if self.source else "PDF Document",
            author=self.metadata.get("author"),
            date=self.metadata.get("creation_date") or self.metadata.get("mod_date"),
            generator=self.metadata.get("creator") or self.metadata.get("producer"),
            description=self.metadata.get("subject"),
            extra={
                "pdf": {
                    "page_count": self.page_count,
                    "format": self.metadata.get("format"),
                    "encrypted": self.metadata.get("encrypted", False),
                    "permissions": self.metadata.get("permissions"),
                },
                "extraction_info": dict(self.extraction_info),
            },
        )

        doc_blocks: List[Block] = []
        doc_tables: List[Dict[str, Any]] = []
        doc_images: List[Dict[str, Any]] = []
        doc_links: List[Dict[str, Any]] = []

        for page in self.pages:
            for b in page.blocks:
                b_extra = dict(b.extra)
                b_extra.update({
                    "page_number": b.page_number,
                    "source_method": b.source_method,
                    "confidence": b.confidence,
                    "bbox": b.bbox.to_list() if b.bbox else None,
                    "font_name": b.font_name,
                    "font_size": b.font_size,
                    "is_bold": b.is_bold,
                    "is_italic": b.is_italic,
                })

                if b.type == "heading":
                    level = b.extra.get("level", 1)
                    doc_blocks.append(HeadingBlock(
                        id=b.block_id,
                        level=level,
                        text=b.text,
                        extra=b_extra,
                    ))
                elif b.type == "list":
                    items = b.extra.get("items", [b.text])
                    doc_blocks.append(ListBlock(
                        id=b.block_id,
                        ordered=b.extra.get("ordered", False),
                        items=items,
                        extra=b_extra,
                    ))
                elif b.type == "table":
                    headers = b.extra.get("headers", [])
                    rows = b.extra.get("rows", [])
                    doc_blocks.append(TableBlock(
                        id=b.block_id,
                        headers=headers,
                        rows=rows,
                        caption=b.extra.get("caption"),
                        extra=b_extra,
                    ))
                elif b.type == "formula":
                    doc_blocks.append(MathBlock(
                        id=b.block_id,
                        latex=b.text,
                        math_type="display" if b.extra.get("display", True) else "inline",
                        original_format="latex",
                        extra=b_extra,
                    ))
                elif b.type == "code":
                    doc_blocks.append(CodeBlock(
                        id=b.block_id,
                        code=b.text,
                        language=b.extra.get("language"),
                        extra=b_extra,
                    ))
                elif b.type == "image":
                    doc_blocks.append(ImageBlock(
                        id=b.block_id,
                        src=b.extra.get("src", ""),
                        alt=b.text,
                        caption=b.text,
                        extra=b_extra,
                    ))
                else:

                    doc_blocks.append(ParagraphBlock(
                        id=b.block_id,
                        text=b.text,
                        extra=b_extra,
                    ))

            for t in page.tables:
                doc_tables.append(t.to_dict())

            for img in page.images:
                doc_images.append(img.to_dict())

            for lk in page.links:
                doc_links.append(dict(lk))

        unified_doc = Document(
            schema_version="1.0",
            source=self.source,
            source_type="pdf",
            title=meta.title or "PDF Document",
            text=self.text,
            markdown=self.markdown,
            metadata=meta,
            blocks=doc_blocks,
            tables=doc_tables,
            images=doc_images,
            links=doc_links,
            chunks=list(self.chunks),
            warnings=list(self.warnings),
            stats=dict(self.stats),
        )
        unified_doc.update_stats()
        return unified_doc
