
import json
from typing import Any, Dict, List, Optional
import yaml

from .models import (
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
    EmbedBlock,
    Document,
)

def export_markdown(doc: Document, include_frontmatter: bool = True) -> str:

    parts: List[str] = []

    if include_frontmatter:
        fm_data = {
            "source": doc.source,
            "source_type": doc.source_type,
            "title": doc.title or None,
            "author": doc.metadata.author,
            "date": doc.metadata.date,
            "text_length": len(doc.text),
        }

        fm_yaml = yaml.safe_dump(fm_data, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    def render_list(block: ListBlock, indent_level: int = 0) -> List[str]:
        lines = []
        indent = "  " * indent_level
        for idx, item in enumerate(block.items):
            prefix = f"{block.start + idx}. " if block.ordered else "- "
            if isinstance(item, dict):
                text = item.get("text", "")
                lines.append(f"{indent}{prefix}{text}")
                nested = item.get("nested")
                if nested:
                    nested_block = ListBlock(
                        ordered=nested.get("ordered", False),
                        start=nested.get("start", 1),
                        items=nested.get("items", []),
                    )
                    lines.extend(render_list(nested_block, indent_level + 1))
            else:
                lines.append(f"{indent}{prefix}{item}")
        return lines

    for block in doc.blocks:
        if isinstance(block, HeadingBlock):
            prefix = "#" * max(1, min(6, block.level))
            parts.append(f"{prefix} {block.text}\n")

        elif isinstance(block, ParagraphBlock):
            if block.text.strip():
                parts.append(f"{block.text.strip()}\n")

        elif isinstance(block, ListBlock):
            list_lines = render_list(block)
            if list_lines:
                parts.append("\n".join(list_lines) + "\n")

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
                    padded_row = clean_row + [""] * max(0, len(clean_headers) - len(clean_row))
                    tbl_lines.append("| " + " | ".join(padded_row[:len(clean_headers)]) + " |")
                parts.append("\n".join(tbl_lines) + "\n")

        elif isinstance(block, CodeBlock):
            lang = block.language or ""
            parts.append(f"```{lang}\n{block.code}\n```\n")

        elif isinstance(block, MathBlock):
            if block.math_type == "display":
                parts.append(f"$$\n{block.latex}\n$$\n")
            else:
                parts.append(f"${block.latex}$\n")

        elif isinstance(block, BlockquoteBlock):
            quote_text = "\n".join(f"> {line}" for line in block.text.splitlines())
            parts.append(f"{quote_text}\n")

        elif isinstance(block, ImageBlock):
            title_part = f' "{block.title}"' if block.title else ""
            caption_part = f"\n*{block.caption}*" if block.caption else ""
            parts.append(f"![{block.alt}]({block.src}{title_part}){caption_part}\n")

        elif isinstance(block, LinkBlock):
            parts.append(f"[{block.text}]({block.href})\n")

        elif isinstance(block, EmbedBlock):
            if block.embed_type == "svg":
                parts.append(f"**[SVG Diagram: {block.title}]**\n")
            else:
                parts.append(f"[{block.embed_type.upper()}: {block.title or block.src}]({block.src})\n")

    return "\n".join(parts).strip() + "\n"

def export_text(doc: Document) -> str:

    parts: List[str] = []

    def render_plain_list(block: ListBlock, indent_level: int = 0) -> List[str]:
        lines = []
        indent = "  " * indent_level
        for idx, item in enumerate(block.items):
            prefix = f"{block.start + idx}. " if block.ordered else "• "
            if isinstance(item, dict):
                text = item.get("text", "")
                lines.append(f"{indent}{prefix}{text}")
                nested = item.get("nested")
                if nested:
                    nested_block = ListBlock(
                        ordered=nested.get("ordered", False),
                        start=nested.get("start", 1),
                        items=nested.get("items", []),
                    )
                    lines.extend(render_plain_list(nested_block, indent_level + 1))
            else:
                lines.append(f"{indent}{prefix}{item}")
        return lines

    for block in doc.blocks:
        if isinstance(block, HeadingBlock):
            if block.level == 1:
                parts.append(f"{block.text}\n{'=' * len(block.text)}\n")
            elif block.level == 2:
                parts.append(f"{block.text}\n{'-' * len(block.text)}\n")
            else:
                parts.append(f"{block.text}\n")

        elif isinstance(block, ParagraphBlock):
            if block.text.strip():
                parts.append(f"{block.text.strip()}\n")

        elif isinstance(block, ListBlock):
            list_lines = render_plain_list(block)
            if list_lines:
                parts.append("\n".join(list_lines) + "\n")

        elif isinstance(block, TableBlock):
            tbl_lines = []
            if block.caption:
                tbl_lines.append(f"[Table: {block.caption}]")
            if block.headers:
                tbl_lines.append("\t".join(block.headers))
                for row in block.rows:
                    tbl_lines.append("\t".join(row))
            if tbl_lines:
                parts.append("\n".join(tbl_lines) + "\n")

        elif isinstance(block, CodeBlock):
            parts.append(f"{block.code}\n")

        elif isinstance(block, MathBlock):
            parts.append(f"{block.latex}\n")

        elif isinstance(block, BlockquoteBlock):
            parts.append(f"  \"{block.text}\"\n")

        elif isinstance(block, ImageBlock):
            parts.append(f"[Image: {block.alt or block.caption or block.src}]\n")

        elif isinstance(block, LinkBlock):
            parts.append(f"{block.text} ({block.href})\n")

        elif isinstance(block, EmbedBlock):
            if block.embed_type == "svg":
                parts.append(f"[SVG Diagram: {block.title}]\n")
            else:
                parts.append(f"[{block.embed_type.upper()}: {block.title or block.src}]\n")

    return "\n".join(parts).strip() + "\n"

def export_json(doc: Document, indent: int = 2) -> str:

    doc_dict = doc.to_dict()
    return json.dumps(doc_dict, indent=indent, ensure_ascii=False)
