
import json
from typing import Any, Dict, List, Optional, Union
import yaml

from .models import WorkbookModel, WorksheetModel, TableRange
from common.models import Document, _safe_serialize
from common.exporters import export_markdown as common_export_md, export_text as common_export_txt

def _clean_cell_str(val: Any) -> str:

    if val is None:
        return ""
    s = str(val).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("|", "\\|").strip()

def export_markdown(target: Union[WorkbookModel, Document], include_frontmatter: bool = True) -> str:

    if isinstance(target, Document):

        wb_data = target.metadata.extra.get("workbook")
        if not wb_data:
            return common_export_md(target, include_frontmatter=include_frontmatter)

        return common_export_md(target, include_frontmatter=include_frontmatter)

    wb: WorkbookModel = target
    parts: List[str] = []

    if include_frontmatter:
        fm_data: Dict[str, Any] = {
            "source": wb.source,
            "source_type": "xlsx",
            "title": wb.title or None,
            "sheet_count": len(wb.sheets),
            "sheets": [s.name for s in wb.sheets],
        }
        if wb.metadata.author:
            fm_data["author"] = wb.metadata.author
        if wb.metadata.date:
            fm_data["date"] = wb.metadata.date

        fm_yaml = yaml.safe_dump(fm_data, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    parts.append(f"# {wb.title}\n")

    for sheet in wb.sheets:
        vis_suffix = "" if sheet.is_visible else " *(Hidden)*"
        parts.append(f"## Sheet: {sheet.name}{vis_suffix}\n")

        if sheet.comments:
            comment_lines = [f"- **{c['coordinate']}**: {c['text']}" for c in sheet.comments if c.get("text")]
            if comment_lines:
                parts.append("**Cell Notes:**")
                parts.append("\n".join(comment_lines) + "\n")

        if sheet.tables:
            for tbl in sheet.tables:
                if tbl.name and tbl.name != sheet.name:
                    parts.append(f"### Table: {tbl.name}\n")

                clean_headers = [_clean_cell_str(h) for h in tbl.headers]
                if not clean_headers:
                    continue

                col_count = len(clean_headers)
                tbl_lines = [
                    "| " + " | ".join(clean_headers) + " |",
                    "| " + " | ".join(["---"] * col_count) + " |",
                ]

                for row in tbl.rows:
                    clean_row = [_clean_cell_str(c) for c in row]

                    padded = clean_row + [""] * max(0, col_count - len(clean_row))
                    tbl_lines.append("| " + " | ".join(padded[:col_count]) + " |")

                parts.append("\n".join(tbl_lines) + "\n")

        elif sheet.total_rows > 0 and sheet.total_cols > 0:
            matrix = sheet.to_matrix(use_inherited_merged=True)
            if matrix:
                headers = [_clean_cell_str(c) for c in matrix[0]]
                col_count = len(headers)
                tbl_lines = [
                    "| " + " | ".join(headers) + " |",
                    "| " + " | ".join(["---"] * col_count) + " |",
                ]
                for row in matrix[1:]:
                    clean_row = [_clean_cell_str(c) for c in row]
                    padded = clean_row + [""] * max(0, col_count - len(clean_row))
                    tbl_lines.append("| " + " | ".join(padded[:col_count]) + " |")
                parts.append("\n".join(tbl_lines) + "\n")
        else:
            parts.append("*(Empty sheet)*\n")

        for chart in sheet.charts:
            chart_title = chart.get("title", "Chart")
            chart_type = chart.get("type", "Chart")
            parts.append(f"**[Chart: {chart_title} ({chart_type})]**\n")

        for img in sheet.images:
            img_path = img.get("path", "")
            img_name = img.get("name", "Image")
            parts.append(f"![{img_name}]({img_path})\n")

    return "\n".join(parts).strip() + "\n"

def export_text(target: Union[WorkbookModel, Document]) -> str:

    if isinstance(target, Document):
        return common_export_txt(target)

    wb: WorkbookModel = target
    parts: List[str] = []

    banner = "=" * 80
    parts.append(banner)
    parts.append(f"WORKBOOK: {wb.title}")
    parts.append(banner)
    parts.append("")

    for sheet in wb.sheets:
        sheet_sep = "-" * 80
        vis_suffix = "" if sheet.is_visible else " [HIDDEN]"
        parts.append(sheet_sep)
        parts.append(f"SHEET: {sheet.name}{vis_suffix}")
        parts.append(sheet_sep)

        if sheet.tables:
            for tbl in sheet.tables:
                if tbl.name and tbl.name != sheet.name:
                    parts.append(f"[Table: {tbl.name}]")
                if tbl.headers:
                    parts.append("\t".join(str(h) if h is not None else "" for h in tbl.headers))
                for row in tbl.rows:
                    parts.append("\t".join(str(c) if c is not None else "" for c in row))
                parts.append("")
        elif sheet.total_rows > 0 and sheet.total_cols > 0:
            matrix = sheet.to_matrix(use_inherited_merged=True)
            for row in matrix:
                parts.append("\t".join(str(c) if c is not None else "" for c in row))
            parts.append("")
        else:
            parts.append("[Empty Sheet]")
            parts.append("")

        for chart in sheet.charts:
            parts.append(f"[Chart: {chart.get('title')} ({chart.get('type')})]")

        for img in sheet.images:
            parts.append(f"[Image: {img.get('name')} -> {img.get('path')}]")

        parts.append("")

    return "\n".join(parts).strip() + "\n"

def export_json(target: Union[WorkbookModel, Document], indent: int = 2) -> str:

    if isinstance(target, Document):
        d = target.to_dict()
    else:
        d = target.to_dict()

    return json.dumps(d, indent=indent, ensure_ascii=False)
