
import json
import re
from typing import Any, Dict, List, Optional, Union
import yaml

from .models import BookModel, ChapterModel, NavigationItem
from common.models import (
    Document,
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
)
from common.exporters import (
    export_markdown as common_export_md,
    export_text as common_export_txt,
)

def _slugify(text: str) -> str:

    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[-\s]+", "-", s)

def _render_toc_markdown(nav_items: List[NavigationItem], indent_level: int = 0) -> List[str]:

    lines: List[str] = []
    indent = "  " * indent_level

    for item in nav_items:
        anchor = item.anchor or _slugify(item.title)
        link = f"#{anchor}" if anchor else ""
        if link:
            lines.append(f"{indent}- [{item.title}]({link})")
        else:
            lines.append(f"{indent}- {item.title}")

        if item.children:
            lines.extend(_render_toc_markdown(item.children, indent_level + 1))

    return lines

def _render_block_markdown(block: Block) -> str:

    if isinstance(block, HeadingBlock):
        prefix = "#" * max(1, min(6, block.level))
        return f"{prefix} {block.text}\n"

    elif isinstance(block, ParagraphBlock):
        return f"{block.text.strip()}\n" if block.text.strip() else ""

    elif isinstance(block, ListBlock):
        lines = []
        for idx, itm in enumerate(block.items):
            prefix = f"{block.start + idx}. " if block.ordered else "- "
            if isinstance(itm, dict):
                lines.append(f"{prefix}{itm.get('text', '')}")
            else:
                lines.append(f"{prefix}{itm}")
        return "\n".join(lines) + "\n" if lines else ""

    elif isinstance(block, TableBlock):
        tbl_lines = []
        if block.caption:
            tbl_lines.append(f"*{block.caption}*\n")
        if block.headers:
            clean_headers = [str(h).replace("|", "\\|").replace("\n", " ").strip() for h in block.headers]
            tbl_lines.append("| " + " | ".join(clean_headers) + " |")
            tbl_lines.append("| " + " | ".join(["---"] * len(clean_headers)) + " |")
            for row in block.rows:
                clean_row = [str(c).replace("|", "\\|").replace("\n", " ").strip() for c in row]
                padded = clean_row + [""] * max(0, len(clean_headers) - len(clean_row))
                tbl_lines.append("| " + " | ".join(padded[:len(clean_headers)]) + " |")
            return "\n".join(tbl_lines) + "\n"

    elif isinstance(block, CodeBlock):
        lang = block.language or ""
        return f"```{lang}\n{block.code}\n```\n"

    elif isinstance(block, MathBlock):
        if block.math_type == "display":
            return f"$$\n{block.latex}\n$$\n"
        return f"${block.latex}$"

    elif isinstance(block, BlockquoteBlock):
        return "\n".join(f"> {line}" for line in block.text.splitlines()) + "\n"

    elif isinstance(block, ImageBlock):
        title_str = f' "{block.title}"' if block.title else ""
        return f"![{block.alt}]({block.src}{title_str})\n"

    elif isinstance(block, LinkBlock):
        return f"[{block.text}]({block.href})\n"

    return ""

def export_markdown(
    target: Union[BookModel, Document],
    include_frontmatter: bool = True,
    include_toc: bool = True,
    include_nonlinear: bool = False,
) -> str:

    if isinstance(target, Document):
        return common_export_md(target, include_frontmatter=include_frontmatter)

    book: BookModel = target
    parts: List[str] = []

    if include_frontmatter:
        fm_data: Dict[str, Any] = {
            "source": book.source,
            "source_type": "epub",
            "title": book.title or None,
            "author": book.metadata.author,
            "language": book.metadata.language,
            "chapter_count": len(book.chapters),
            "epub_version": book.epub_version,
        }
        if book.metadata.date:
            fm_data["date"] = book.metadata.date

        fm_yaml = yaml.safe_dump(fm_data, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    parts.append(f"# {book.title}\n")

    if book.cover_image_path:
        parts.append(f"![Cover Image]({book.cover_image_path})\n")

    if include_toc and book.navigation:
        parts.append("## Table of Contents\n")
        toc_lines = _render_toc_markdown(book.navigation)
        if toc_lines:
            parts.append("\n".join(toc_lines) + "\n")
        parts.append("---\n")

    first_chapter = True
    for ch in book.chapters:
        if not ch.linear and not include_nonlinear:
            continue

        if not first_chapter:
            parts.append("\n---\n")
        first_chapter = False

        ch_title = ch.title or f"Chapter {ch.spine_index + 1}"
        parts.append(f"# {ch_title}\n")

        for b in ch.blocks:
            if isinstance(b, HeadingBlock) and b.level == 1 and b.text.strip().lower() == ch_title.strip().lower():
                continue
            md_str = _render_block_markdown(b)
            if md_str:
                parts.append(md_str)

        if ch.footnotes:
            parts.append("\n### Footnotes\n")
            for fn in ch.footnotes:
                parts.append(f"[^{fn.id}]: {fn.text}\n")

    return "\n".join(parts).strip() + "\n"

def export_text(
    target: Union[BookModel, Document],
    include_toc: bool = True,
    include_nonlinear: bool = False,
) -> str:

    if isinstance(target, Document):
        return common_export_txt(target)

    book: BookModel = target
    parts: List[str] = []

    banner = "=" * 80
    parts.append(banner)
    parts.append(f"BOOK: {book.title}")
    parts.append(banner)
    if book.metadata.author:
        parts.append(f"Author: {book.metadata.author}")
    if book.metadata.language:
        parts.append(f"Language: {book.metadata.language}")
    parts.append("")

    if include_toc and book.navigation:
        parts.append(banner)
        parts.append("TABLE OF CONTENTS")
        parts.append(banner)

        def print_toc_txt(nav_items: List[NavigationItem], indent_level: int = 0):
            indent = "  " * indent_level
            for item in nav_items:
                parts.append(f"{indent}• {item.title}")
                if item.children:
                    print_toc_txt(item.children, indent_level + 1)

        print_toc_txt(book.navigation)
        parts.append("")

    for ch in book.chapters:
        if not ch.linear and not include_nonlinear:
            continue

        ch_sep = "-" * 80
        ch_title = ch.title or f"Chapter {ch.spine_index + 1}"
        parts.append(ch_sep)
        parts.append(f"{ch_title.upper()}")
        parts.append(ch_sep)

        for b in ch.blocks:
            if isinstance(b, HeadingBlock):
                if b.level == 1 and b.text.strip().lower() == ch_title.strip().lower():
                    continue
                parts.append(f"\n{b.text}\n")
            elif isinstance(b, ParagraphBlock):
                if b.text.strip():
                    parts.append(b.text.strip())
            elif isinstance(b, ListBlock):
                for idx, itm in enumerate(b.items):
                    prefix = f"{b.start + idx}. " if b.ordered else "• "
                    text = itm.get("text", "") if isinstance(itm, dict) else str(itm)
                    parts.append(f"{prefix}{text}")
            elif isinstance(b, TableBlock):
                if b.headers:
                    parts.append("\t".join(b.headers))
                for row in b.rows:
                    parts.append("\t".join(row))
            elif isinstance(b, CodeBlock):
                parts.append(b.code)
            elif isinstance(b, MathBlock):
                parts.append(b.latex)
            elif isinstance(b, BlockquoteBlock):
                parts.append(f'  "{b.text}"')
            elif isinstance(b, ImageBlock):
                parts.append(f"[Image: {b.alt or b.src}]")

        if ch.footnotes:
            parts.append("\nFootnotes:")
            for fn in ch.footnotes:
                parts.append(f"  [{fn.id}]: {fn.text}")

        parts.append("")

    return "\n".join(parts).strip() + "\n"

def export_json(target: Union[BookModel, Document], indent: int = 2) -> str:

    if isinstance(target, Document):
        d = target.to_dict()
    else:
        d = target.to_dict()

    return json.dumps(d, indent=indent, ensure_ascii=False)
