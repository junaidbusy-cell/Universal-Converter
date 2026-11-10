
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union

from common.models import (
    Document,
    Metadata,
    Block,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    ImageBlock,
    EmbedBlock,
    _safe_serialize,
)

@dataclass
class CellModel:

    coordinate: str
    row: int
    col: int
    value: Any = None
    raw_value: Optional[str] = None
    formula: Optional[str] = None
    cached_value: Any = None
    data_type: str = "empty"
    number_format: Optional[str] = None
    hyperlink: Optional[str] = None
    comment: Optional[str] = None
    is_merged: bool = False
    merge_origin: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:

        d = {
            "coordinate": self.coordinate,
            "row": self.row,
            "col": self.col,
            "value": _safe_serialize(self.value),
            "raw_value": self.raw_value,
            "data_type": self.data_type,
        }
        if self.formula:
            d["formula"] = self.formula
        if self.cached_value is not None:
            d["cached_value"] = _safe_serialize(self.cached_value)
        if self.number_format:
            d["number_format"] = self.number_format
        if self.hyperlink:
            d["hyperlink"] = self.hyperlink
        if self.comment:
            d["comment"] = self.comment
        if self.is_merged:
            d["is_merged"] = True
            d["merge_origin"] = self.merge_origin
        return d

@dataclass
class TableRange:

    name: str
    range_str: str
    start_row: int
    end_row: int
    start_col: int
    end_col: int
    headers: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    is_formal: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "range": self.range_str,
            "start_row": self.start_row,
            "end_row": self.end_row,
            "start_col": self.start_col,
            "end_col": self.end_col,
            "is_formal": self.is_formal,
            "headers": list(self.headers),
            "rows": _safe_serialize(self.rows),
        }

@dataclass
class WorksheetModel:

    name: str
    index: int
    state: str = "visible"
    is_visible: bool = True
    min_row: int = 1
    max_row: int = 1
    min_col: int = 1
    max_col: int = 1
    total_rows: int = 0
    total_cols: int = 0
    tables: List[TableRange] = field(default_factory=list)
    cells: Dict[str, CellModel] = field(default_factory=dict)
    merged_ranges: List[str] = field(default_factory=list)
    charts: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    comments: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def get_cell(self, coord: str) -> Optional[CellModel]:

        return self.cells.get(coord)

    def to_matrix(self, use_inherited_merged: bool = True) -> List[List[Any]]:

        if self.total_rows == 0 or self.total_cols == 0:
            return []

        matrix: List[List[Any]] = []
        for r in range(self.min_row, self.max_row + 1):
            row_vals: List[Any] = []
            for c in range(self.min_col, self.max_col + 1):
                from openpyxl.utils import get_column_letter
                coord = f"{get_column_letter(c)}{r}"
                cell = self.cells.get(coord)
                if cell is None:
                    row_vals.append("")
                else:
                    val = cell.value
                    if val is None and cell.formula:
                        val = cell.cached_value if cell.cached_value is not None else cell.formula
                    row_vals.append(val if val is not None else "")
            matrix.append(row_vals)
        return matrix

    def to_dict(self) -> Dict[str, Any]:

        return {
            "name": self.name,
            "index": self.index,
            "state": self.state,
            "is_visible": self.is_visible,
            "dimensions": {
                "min_row": self.min_row,
                "max_row": self.max_row,
                "min_col": self.min_col,
                "max_col": self.max_col,
                "total_rows": self.total_rows,
                "total_cols": self.total_cols,
            },
            "tables": [t.to_dict() for t in self.tables],
            "merged_ranges": list(self.merged_ranges),
            "cells": {coord: cell.to_dict() for coord, cell in self.cells.items()},
            "charts": _safe_serialize(self.charts),
            "images": _safe_serialize(self.images),
            "comments": _safe_serialize(self.comments),
            "warnings": list(self.warnings),
        }

@dataclass
class WorkbookModel:

    source: str = ""
    title: str = ""
    metadata: Metadata = field(default_factory=Metadata)
    sheets: List[WorksheetModel] = field(default_factory=list)
    defined_names: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def update_stats(self) -> None:

        total_cells = sum(len(s.cells) for s in self.sheets)
        total_tables = sum(len(s.tables) for s in self.sheets)
        total_images = sum(len(s.images) for s in self.sheets)
        total_charts = sum(len(s.charts) for s in self.sheets)
        visible_sheets = sum(1 for s in self.sheets if s.is_visible)

        self.stats.update({
            "sheet_count": len(self.sheets),
            "visible_sheet_count": visible_sheets,
            "total_cell_count": total_cells,
            "total_table_count": total_tables,
            "total_image_count": total_images,
            "total_chart_count": total_charts,
            "warning_count": len(self.warnings),
        })

    def to_dict(self) -> Dict[str, Any]:

        return {
            "source": self.source,
            "title": self.title,
            "metadata": self.metadata.to_dict(),
            "sheets": [s.to_dict() for s in self.sheets],
            "defined_names": _safe_serialize(self.defined_names),
            "stats": dict(self.stats),
            "warnings": list(self.warnings),
        }

    def to_document(self) -> Document:

        self.update_stats()
        doc = Document(
            schema_version="1.0",
            source=self.source,
            source_type="xlsx",
            title=self.title or self.metadata.title or "Spreadsheet",
            metadata=self.metadata,
        )

        doc.metadata.extra["workbook"] = self.to_dict()
        doc.metadata.extra["sheet_names"] = [s.name for s in self.sheets]

        for w in self.warnings:
            doc.add_warning(w)

        for s in self.sheets:
            for w in s.warnings:
                doc.add_warning(f"[{s.name}] {w}")

            visibility_suffix = "" if s.is_visible else " (Hidden)"
            sheet_title = f"Sheet: {s.name}{visibility_suffix}"
            doc.blocks.append(HeadingBlock(level=2, text=sheet_title))

            if s.comments:
                comments_text = "; ".join(f"{c['coordinate']}: {c['text']}" for c in s.comments if c.get("text"))
                if comments_text:
                    doc.blocks.append(ParagraphBlock(text=f"Sheet Notes: {comments_text}"))

            if s.tables:
                for tbl in s.tables:
                    clean_headers = [str(h) if h is not None else "" for h in tbl.headers]
                    clean_rows = [
                        [str(cell_val) if cell_val is not None else "" for cell_val in row]
                        for row in tbl.rows
                    ]
                    tbl_caption = f"{s.name} - {tbl.name}" if tbl.name != s.name else s.name
                    doc.blocks.append(TableBlock(
                        headers=clean_headers,
                        rows=clean_rows,
                        caption=tbl_caption,
                    ))

                    doc.tables.append({
                        "sheet": s.name,
                        "name": tbl.name,
                        "range": tbl.range_str,
                        "is_formal": tbl.is_formal,
                        "headers": clean_headers,
                        "rows": clean_rows,
                    })
            elif s.total_rows > 0 and s.total_cols > 0:

                matrix = s.to_matrix(use_inherited_merged=True)
                if matrix:
                    headers = [str(c) if c is not None else "" for c in matrix[0]]
                    rows = [
                        [str(c) if c is not None else "" for c in r]
                        for r in matrix[1:]
                    ]
                    doc.blocks.append(TableBlock(
                        headers=headers,
                        rows=rows,
                        caption=s.name,
                    ))
                    doc.tables.append({
                        "sheet": s.name,
                        "name": s.name,
                        "range": f"R{s.min_row}C{s.min_col}:R{s.max_row}C{s.max_col}",
                        "is_formal": False,
                        "headers": headers,
                        "rows": rows,
                    })

            for chart in s.charts:
                chart_title = chart.get("title") or "Chart"
                doc.blocks.append(EmbedBlock(
                    embed_type="chart",
                    title=f"{s.name} - {chart_title}",
                    src=None,
                ))

            for img in s.images:
                img_path = img.get("path") or ""
                img_name = img.get("name") or "Image"
                doc.blocks.append(ImageBlock(
                    src=img_path,
                    alt=img_name,
                    title=f"{s.name} - {img_name}",
                ))
                doc.images.append(img)

        doc.update_stats()
        return doc
