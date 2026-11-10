
import json
from typing import Any, Dict, List, Optional
import yaml

from .models import ImageOCRDocument, OCRPage, OCRRegion, OCRTable, OCRFormula

def _escape_table_cell(text: str) -> str:

    if not text:
        return ""
    clean = text.replace("\n", " ").replace("\r", "")
    return clean.replace("|", "\\|").strip()

def export_markdown(
    doc: ImageOCRDocument,
    include_frontmatter: bool = True,
) -> str:

    parts: List[str] = []

    if include_frontmatter:
        fm_data = {
            "source": doc.source,
            "source_type": doc.source_type,
            "page_count": len(doc.pages),
            "language": doc.ocr_info.get("language", "en"),
            "engine": doc.ocr_info.get("engine", "PaddleOCR"),
            "model": doc.ocr_info.get("model", "PP-OCRv6"),
            "tier": doc.ocr_info.get("tier", "medium"),
            "text_length": len(doc.text),
        }
        fm_yaml = yaml.safe_dump(fm_data, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    multi_page = len(doc.pages) > 1

    for page in doc.pages:
        if multi_page:
            parts.append(f"## Page {page.page_number}\n")

        for r in page.regions:
            reg_type = r.type.lower()
            text = r.text.strip()
            if not text:
                continue

            if reg_type == "heading":
                level = r.extra.get("level", 2)
                prefix = "#" * max(1, min(6, level))
                parts.append(f"{prefix} {text}\n")
            elif reg_type == "code":
                parts.append(f"```\n{text}\n```\n")
            elif reg_type == "list":
                if not text.startswith(("-", "*", "•", "1.")):
                    parts.append(f"- {text}\n")
                else:
                    parts.append(f"{text}\n")
            elif reg_type == "quote":
                parts.append(f"> {text}\n")
            elif reg_type == "formula":
                if text.startswith("$$") and text.endswith("$$"):
                    parts.append(f"{text}\n")
                else:
                    parts.append(f"$$\n{text}\n$$\n")
            else:
                parts.append(f"{text}\n")

        for table in page.tables:
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
            parts.append(f"{tbl_md}\n")

        for formula in page.formulas:
            if formula.display:
                parts.append(f"$$\n{formula.latex}\n$$\n")
            else:
                parts.append(f"${formula.latex}$\n")

    return "\n".join(parts).strip() + "\n"

def export_text(doc: ImageOCRDocument) -> str:

    lines: List[str] = []
    multi_page = len(doc.pages) > 1

    for page in doc.pages:
        if multi_page:
            banner = "=" * 50
            lines.append(banner)
            lines.append(f"PAGE {page.page_number}")
            lines.append(banner)
            lines.append("")

        for r in page.regions:
            text = r.text.strip()
            if not text:
                continue
            if r.type == "heading":
                lines.append(text.upper() if len(text) < 40 else text)
                lines.append("")
            else:
                lines.append(text)
                lines.append("")

        for table in page.tables:
            if table.headers:
                lines.append("  |  ".join(table.headers))
                lines.append("-" * 40)
            for row in table.rows:
                lines.append("  |  ".join(row))
            lines.append("")

        for formula in page.formulas:
            lines.append(f"[Formula: {formula.latex}]")
            lines.append("")

    return "\n".join(lines).strip() + "\n"

def export_json(doc: ImageOCRDocument, indent: int = 2) -> str:

    return json.dumps(doc.to_dict(), indent=indent, ensure_ascii=False)
