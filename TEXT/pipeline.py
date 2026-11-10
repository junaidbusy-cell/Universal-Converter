
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
import charset_normalizer

from common.models import (
    Document,
    Metadata,
    Block,
    HeadingBlock,
    ParagraphBlock,
    ListBlock,
    TableBlock,
    CodeBlock,
    BlockquoteBlock,
)
from common.exporters import export_markdown, export_text, export_json
from common.chunker import chunk_document
from common.validator import validate_extraction

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".text",
    ".log",
    ".err",
    ".out",
    ".md",
    ".markdown",
    ".mdown",
    ".mkd",
    ".rst",
}

def _read_file_text(path: Path) -> str:

    raw = path.read_bytes()
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    best = charset_normalizer.from_bytes(raw).best()
    if best is not None:
        return str(best)
    return raw.decode("latin1", errors="replace")

def _parse_frontmatter(text: str) -> Tuple[Metadata, str]:

    meta = Metadata()
    content = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_str = parts[1].strip()
            content = parts[2].lstrip()
            try:
                data = yaml.safe_load(fm_str)
                if isinstance(data, dict):
                    meta.title = data.get("title")
                    meta.author = data.get("author")
                    meta.date = str(data.get("date")) if data.get("date") else None
                    meta.language = data.get("language")
                    meta.description = data.get("description")
                    meta.extra = {k: v for k, v in data.items() if k not in ("title", "author", "date", "language", "description")}
            except Exception:
                pass
    return meta, content

def _parse_markdown_blocks(text: str) -> List[Block]:

    blocks: List[Block] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1
            blocks.append(CodeBlock(code="\n".join(code_lines), language=lang if lang else None))
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            blocks.append(HeadingBlock(level=level, text=heading_text))
            i += 1
            continue

        if i + 1 < n and lines[i + 1].strip() and (
            re.match(r"^={2,}$", lines[i + 1].strip()) or re.match(r"^-{2,}$", lines[i + 1].strip())
        ):
            level = 1 if lines[i + 1].strip().startswith("=") else 2
            blocks.append(HeadingBlock(level=level, text=stripped))
            i += 2
            continue

        if stripped.startswith(">"):
            quote_lines = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(re.sub(r"^>\s?", "", lines[i].strip()))
                i += 1
            blocks.append(BlockquoteBlock(text="\n".join(quote_lines)))
            continue

        if stripped.startswith("|") and stripped.endswith("|") and i + 1 < n and "|" in lines[i + 1]:
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            i += 1

            if i < n and re.match(r"^[\|\s\:\-]+$", lines[i].strip()):
                i += 1
            table_rows: List[List[str]] = []
            while i < n and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                table_rows.append(row_cells)
                i += 1
            blocks.append(TableBlock(headers=header_cells, rows=table_rows))
            continue

        list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if list_match:
            is_ordered = bool(re.match(r"^\d+\.", list_match.group(2)))
            items: List[str] = []
            while i < n:
                m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[i])
                if not m:
                    break
                items.append(m.group(3).strip())
                i += 1
            blocks.append(ListBlock(ordered=is_ordered, items=items))
            continue

        para_lines = [stripped]
        i += 1
        while i < n:
            next_line = lines[i].strip()
            if not next_line:
                break
            if next_line.startswith(("#", "```", ">", "|", "-", "*", "+")) or re.match(r"^\d+\.\s+", next_line):
                break
            para_lines.append(next_line)
            i += 1
        blocks.append(ParagraphBlock(text=" ".join(para_lines)))

    return blocks

def _parse_log_blocks(text: str) -> List[Block]:

    blocks: List[Block] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    log_entry_pattern = re.compile(
        r"^(\[?\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}[^\]]*\]?|\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2})\s+([A-Z]+)?:?\s*(.*)$"
    )

    current_para: List[str] = []

    def flush_para():
        if current_para:
            blocks.append(ParagraphBlock(text="\n".join(current_para)))
            current_para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if "Traceback (most recent call last):" in stripped or (
            current_para and (line.startswith("  File ") or line.startswith("    "))
        ):
            flush_para()
            trace_lines = [line]
            i += 1
            while i < n and (lines[i].startswith(" ") or lines[i].startswith("\t") or "Error:" in lines[i] or "Exception:" in lines[i]):
                trace_lines.append(lines[i])
                i += 1
            blocks.append(CodeBlock(code="\n".join(trace_lines), language="log"))
            continue

        match = log_entry_pattern.match(stripped)
        if match:
            flush_para()
            current_para.append(stripped)
            i += 1
        else:
            current_para.append(stripped)
            i += 1

    flush_para()
    return blocks

def _parse_plain_text_blocks(text: str) -> List[Block]:

    blocks: List[Block] = []
    paragraphs = re.split(r"\n\s*\n", text.strip())

    for p in paragraphs:
        cleaned = p.strip()
        if not cleaned:
            continue
        lines = cleaned.splitlines()

        if len(lines) == 2 and len(lines[1].strip()) >= 3 and (
            set(lines[1].strip()) <= {"="} or set(lines[1].strip()) <= {"-"} or set(lines[1].strip()) <= {"~"}
        ):
            lvl = 1 if "=" in lines[1] else (2 if "-" in lines[1] else 3)
            blocks.append(HeadingBlock(level=lvl, text=lines[0].strip()))
            continue

        if len(lines) == 1 and len(cleaned) < 80 and not cleaned.endswith((".", ",", ";", ":", "!", "?")):
            if cleaned.isupper() or cleaned.istitle():
                blocks.append(HeadingBlock(level=1 if cleaned.isupper() else 2, text=cleaned))
                continue

        if all(re.match(r"^[-*•]\s+", ln.strip()) for ln in lines if ln.strip()):
            items = [re.sub(r"^[-*•]\s+", "", ln.strip()) for ln in lines if ln.strip()]
            blocks.append(ListBlock(ordered=False, items=items))
            continue

        blocks.append(ParagraphBlock(text="\n".join(lines)))

    return blocks

def process_text(
    input_path: Union[str, Path],
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    run_validation: bool = True,
    force: bool = False,
    **kwargs: Any,
) -> Document:

    start_time = time.time()
    path = Path(input_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input text file not found: {path}")

    ext = path.suffix.lower()
    raw_content = _read_file_text(path)

    if ext in (".md", ".markdown", ".mdown", ".mkd"):
        meta, body_text = _parse_frontmatter(raw_content)
        blocks = _parse_markdown_blocks(body_text)
        src_type = "markdown"
    elif ext in (".log", ".err", ".out"):
        meta = Metadata(title=f"{path.stem.replace('_', ' ').title()} Log")
        blocks = _parse_log_blocks(raw_content)
        src_type = "log"
    else:
        meta = Metadata(title=path.stem.replace("_", " ").title())
        blocks = _parse_plain_text_blocks(raw_content)
        src_type = "text"

    if not meta.title or not meta.title.strip():

        for b in blocks:
            if isinstance(b, HeadingBlock) and b.text.strip():
                meta.title = b.text.strip()
                break
        if not meta.title:
            meta.title = path.stem.replace("_", " ").title()

    doc = Document(
        source=str(path),
        source_type=src_type,
        title=meta.title,
        metadata=meta,
        blocks=blocks,
    )

    txt_content = export_text(doc)
    doc.text = txt_content

    md_content = export_markdown(doc, include_frontmatter=True)
    doc.markdown = md_content

    if enable_chunking:
        doc.chunks = chunk_document(
            doc,
            target_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )

    elapsed = time.time() - start_time
    doc.update_stats()
    doc.stats["processing_time_seconds"] = round(elapsed, 4)

    json_content = export_json(doc, indent=2)

    if run_validation:
        is_valid, val_errors = validate_extraction(doc)
        for err in val_errors:
            doc.add_warning(f"Validation notice: {err}")

    target_out_dir = Path(output_dir) if output_dir else Path("output/TEXT")
    doc_out_dir = target_out_dir / path.stem
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    target_format = output_format.lower()
    files_to_write = []
    if target_format in ("md", "all"):
        files_to_write.append((doc_out_dir / f"{path.stem}.md", md_content))
    if target_format in ("txt", "all"):
        files_to_write.append((doc_out_dir / f"{path.stem}.txt", txt_content))
    if target_format in ("json", "all"):
        files_to_write.append((doc_out_dir / f"{path.stem}.json", json_content))

    for out_file, data_str in files_to_write:
        if out_file.exists() and not force:
            continue
        out_file.write_text(data_str, encoding="utf-8")

    return doc
