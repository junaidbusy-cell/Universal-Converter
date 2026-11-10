
import json
from typing import Any, Dict, List, Optional
import yaml

from .models import PDFDocument, PDFPage, PDFBlock, PDFTable, PDFFormula

def _escape_table_cell(text: str) -> str:

    if not text:
        return ""
    clean = text.replace("\n", " ").replace("\r", "")
    return clean.replace("|", "\\|").strip()

def export_markdown(
    doc: PDFDocument,
    include_frontmatter: bool = True,
) -> str:

    parts: List[str] = []

    if include_frontmatter:
        fm_data: Dict[str, Any] = {
            "title": doc.metadata.get("title") or "PDF Document",
            "author": doc.metadata.get("author"),
            "date": doc.metadata.get("creation_date") or doc.metadata.get("mod_date"),
            "source": doc.source,
            "format": doc.metadata.get("format", "PDF"),
            "page_count": len(doc.pages),
        }
        if doc.extraction_info:
            fm_data["extraction"] = {
                "mode": doc.extraction_info.get("mode", "auto"),
                "tier": doc.extraction_info.get("tier"),
                "dpi": doc.extraction_info.get("dpi"),
            }

        cleaned_fm = {k: v for k, v in fm_data.items() if v is not None}
        fm_yaml = yaml.safe_dump(cleaned_fm, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    multi_page = len(doc.pages) > 1

    for page in doc.pages:
        if multi_page:
            parts.append(f"<!-- PAGE {page.page_number} -->\n")

        rendered_table_ids = set()

        for b in page.blocks:
            b_type = b.type.lower()
            text = b.text.strip()
            if not text and b_type != "table":
                continue

            if b_type == "heading":
                level = b.extra.get("level", 2)
                prefix = "#" * max(1, min(6, level))
                parts.append(f"{prefix} {text}\n")
            elif b_type == "code":
                lang = b.extra.get("language", "")
                parts.append(f"```{lang}\n{text}\n```\n")
            elif b_type == "list":
                if not text.startswith(("-", "*", "•", "1.")):
                    parts.append(f"- {text}\n")
                else:
                    parts.append(f"{text}\n")
            elif b_type == "formula":
                if text.startswith("$$") and text.endswith("$$"):
                    parts.append(f"{text}\n")
                else:
                    parts.append(f"$$\n{text}\n$$\n")
            elif b_type == "image":
                src = b.extra.get("src", "")
                parts.append(f"![{text}]({src})\n")
            elif b_type == "table":

                t_id = b.extra.get("table_id")
                if t_id:
                    rendered_table_ids.add(t_id)
                headers = b.extra.get("headers", [])
                rows = b.extra.get("rows", [])
                if headers or rows:
                    if not headers and rows:
                        headers = [f"Col {i+1}" for i in range(len(rows[0]))]
                    hdr_line = "| " + " | ".join(_escape_table_cell(h) for h in headers) + " |"
                    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
                    row_lines = []
                    for row in rows:
                        padded = list(row) + [""] * max(0, len(headers) - len(row))
                        row_lines.append("| " + " | ".join(_escape_table_cell(c) for c in padded[:len(headers)]) + " |")
                    tbl_md = "\n".join([hdr_line, sep_line] + row_lines)
                    parts.append(f"{tbl_md}\n")
            else:

                parts.append(f"{text}\n")

        for table in page.tables:
            if table.table_id in rendered_table_ids:
                continue
            if not table.rows and not table.headers:
                continue
            headers = table.headers if table.headers else [f"Col {i+1}" for i in range(len(table.rows[0]))]
            hdr_line = "| " + " | ".join(_escape_table_cell(h) for h in headers) + " |"
            sep_line = "| " + " | ".join("---" for _ in headers) + " |"
            row_lines = []
            for row in table.rows:
                padded = list(row) + [""] * max(0, len(headers) - len(row))
                row_lines.append("| " + " | ".join(_escape_table_cell(c) for c in padded[:len(headers)]) + " |")

            tbl_md = "\n".join([hdr_line, sep_line] + row_lines)
            if table.caption:
                parts.append(f"*{table.caption}*\n")
            parts.append(f"{tbl_md}\n")
            rendered_table_ids.add(table.table_id)

    return "\n".join(parts).strip() + "\n"

def export_text(doc: PDFDocument) -> str:

    lines: List[str] = []
    multi_page = len(doc.pages) > 1

    for page in doc.pages:
        if multi_page:
            banner = "=" * 50
            lines.append(banner)
            lines.append(f"=== PAGE {page.page_number} ===")
            lines.append(banner)
            lines.append("")

        rendered_table_ids = set()

        for b in page.blocks:
            if b.type == "table":
                t_id = b.extra.get("table_id")
                if t_id:
                    rendered_table_ids.add(t_id)
                headers = b.extra.get("headers", [])
                rows = b.extra.get("rows", [])
                if headers:
                    lines.append("  |  ".join(headers))
                    lines.append("-" * 40)
                for row in rows:
                    lines.append("  |  ".join(row))
                lines.append("")
                continue

            text = b.text.strip()
            if not text:
                continue
            if b.type == "heading":
                lines.append(text.upper() if len(text) < 40 else text)
                lines.append("")
            elif b.type == "formula":
                lines.append(f"[Formula: {text}]")
                lines.append("")
            else:
                lines.append(text)
                lines.append("")

        for table in page.tables:
            if table.table_id in rendered_table_ids:
                continue
            if table.headers:
                lines.append("  |  ".join(table.headers))
                lines.append("-" * 40)
            for row in table.rows:
                lines.append("  |  ".join(row))
            lines.append("")

    return "\n".join(lines).strip() + "\n"

def export_json(doc: PDFDocument, indent: int = 2) -> str:

    return json.dumps(doc.to_dict(), indent=indent, ensure_ascii=False)
