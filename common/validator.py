
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from .models import Document, HeadingBlock, TableBlock

def validate_extraction(doc: Document) -> Tuple[bool, List[str]]:

    errors: List[str] = []

    if not doc.blocks and not doc.warnings:
        errors.append("Document has no extracted blocks and no warnings recorded.")

    for block in doc.blocks:
        if isinstance(block, HeadingBlock):
            if block.level < 1 or block.level > 6:
                errors.append(f"Invalid heading level {block.level} on '{block.text}'.")

        elif isinstance(block, TableBlock):

            num_cols = len(block.headers)
            for r_idx, row in enumerate(block.rows):
                if len(row) != num_cols and num_cols > 0:

                    pass

    return len(errors) == 0, errors

def validate_output_files(
    output_files: List[Path],
    expect_content: bool = True,
) -> Tuple[bool, List[str]]:

    errors: List[str] = []
    required_json_keys = {
        "schema_version",
        "source",
        "source_type",
        "title",
        "text",
        "markdown",
        "metadata",
        "blocks",
        "tables",
        "images",
        "links",
        "chunks",
        "warnings",
        "stats",
    }

    for path in output_files:
        if not path.exists():
            errors.append(f"Expected output file was not created: {path}")
            continue

        size = path.stat().st_size
        if expect_content and size == 0:
            errors.append(f"Output file is empty (0 bytes): {path}")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            errors.append(f"Output file {path} is not valid UTF-8: {e}")
            continue

        if path.suffix.lower() == ".json":
            try:
                data = json.loads(content)
                if data.get("source_type") == "doi":
                    required_keys = {
                        "schema_version",
                        "source",
                        "source_type",
                        "metadata",
                        "content",
                        "references",
                        "text",
                        "markdown",
                        "stats",
                    }
                else:
                    required_keys = required_json_keys
                missing = required_keys - set(data.keys())
                if missing:
                    errors.append(f"JSON output {path} is missing required keys: {sorted(missing)}")
            except json.JSONDecodeError as e:
                errors.append(f"JSON output {path} failed to parse: {e}")

    return len(errors) == 0, errors

def validate_consistency(
    doc: Document,
    md: str,
    txt: str,
    json_str: str,
) -> Tuple[bool, List[str]]:

    errors: List[str] = []

    h1_headings = [b.text for b in doc.blocks if isinstance(b, HeadingBlock) and b.level == 1]
    for h in h1_headings:
        if h not in md:
            errors.append(f"H1 heading '{h}' missing from Markdown output.")

        if h not in txt and h.upper() not in txt:
            errors.append(f"H1 heading '{h}' missing from TXT output.")

    try:
        data = json.loads(json_str)
        if data.get("source_type") == "doi":
            sections = data.get("content", {}).get("sections", [])
            if not sections and len(doc.blocks) > 0 and not doc.warnings:
                errors.append("Section mismatch between PaperModel and JSON output.")
        else:
            if len(data.get("blocks", [])) != len(doc.blocks):
                errors.append("Block count mismatch between Document model and JSON output.")
    except Exception as e:
        errors.append(f"JSON consistency parse failed: {e}")

    return len(errors) == 0, errors
