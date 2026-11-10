
import configparser
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml
from bs4 import BeautifulSoup
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
    ".json",
    ".jsonl",
    ".ndjson",
    ".yaml",
    ".yml",
    ".csv",
    ".tsv",
    ".xml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
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

def _reconstruct_block(d: Dict[str, Any]) -> Block:

    btype = d.get("type", "paragraph")
    bid = d.get("id")
    extra = d.get("extra", {})

    if btype == "heading":
        return HeadingBlock(id=bid, level=d.get("level", 1), text=d.get("text", ""), extra=extra)
    elif btype == "paragraph":
        return ParagraphBlock(id=bid, text=d.get("text", ""), extra=extra)
    elif btype == "list":
        return ListBlock(id=bid, ordered=d.get("ordered", False), start=d.get("start", 1), items=d.get("items", []), extra=extra)
    elif btype == "table":
        return TableBlock(id=bid, headers=d.get("headers", []), rows=d.get("rows", []), caption=d.get("caption"), extra=extra)
    elif btype == "code":
        return CodeBlock(id=bid, code=d.get("code", ""), language=d.get("language"), extra=extra)
    elif btype == "blockquote":
        return BlockquoteBlock(id=bid, text=d.get("text", ""), extra=extra)
    return ParagraphBlock(id=bid, text=d.get("text", str(d)), extra=extra)

def _parse_json_document(raw_text: str, source_path: Path) -> Tuple[Metadata, List[Block], str]:

    meta = Metadata(title=source_path.stem.replace("_", " ").title())
    blocks: List[Block] = []

    try:
        data = json.loads(raw_text)
    except Exception as e:
        blocks.append(CodeBlock(code=raw_text, language="json"))
        return meta, blocks, "json"

    if isinstance(data, dict) and "schema_version" in data and "blocks" in data:
        meta_d = data.get("metadata", {})
        meta = Metadata(
            title=data.get("title") or meta_d.get("title") or meta.title,
            author=meta_d.get("author"),
            date=meta_d.get("date"),
            language=meta_d.get("language"),
            description=meta_d.get("description"),
            extra=meta_d.get("extra", {}),
        )
        for bd in data.get("blocks", []):
            if isinstance(bd, dict):
                blocks.append(_reconstruct_block(bd))
        return meta, blocks, data.get("source_type", "json")

    if isinstance(data, list):
        if data and all(isinstance(row, dict) for row in data):

            headers: List[str] = []
            for item in data:
                for k in item.keys():
                    if k not in headers:
                        headers.append(k)
            rows: List[List[str]] = []
            for item in data:
                rows.append([str(item.get(h, "")) for h in headers])
            blocks.append(HeadingBlock(level=1, text=f"{meta.title} Records ({len(data)} items)"))
            blocks.append(TableBlock(headers=headers, rows=rows, caption=f"Dataset containing {len(data)} records"))
        else:
            blocks.append(HeadingBlock(level=1, text=f"{meta.title} List"))
            blocks.append(ListBlock(ordered=False, items=[str(item) for item in data]))

        blocks.append(CodeBlock(code=json.dumps(data, indent=2), language="json"))
        return meta, blocks, "json"

    if isinstance(data, dict):
        blocks.append(HeadingBlock(level=1, text=meta.title))
        scalar_keys = [k for k, v in data.items() if not isinstance(v, (dict, list))]
        if scalar_keys:
            rows = [[k, str(data[k])] for k in scalar_keys]
            blocks.append(TableBlock(headers=["Property", "Value"], rows=rows, caption="Key-Value Properties"))

        complex_keys = [k for k, v in data.items() if isinstance(v, (dict, list))]
        for k in complex_keys:
            blocks.append(HeadingBlock(level=2, text=k.replace("_", " ").title()))
            sub = data[k]
            if isinstance(sub, list) and sub and all(isinstance(x, dict) for x in sub):
                sub_headers: List[str] = []
                for x in sub:
                    for sk in x.keys():
                        if sk not in sub_headers:
                            sub_headers.append(sk)
                sub_rows = [[str(x.get(sh, "")) for sh in sub_headers] for x in sub]
                blocks.append(TableBlock(headers=sub_headers, rows=sub_rows))
            else:
                blocks.append(CodeBlock(code=json.dumps(sub, indent=2), language="json"))

        return meta, blocks, "json"

    blocks.append(ParagraphBlock(text=str(data)))
    return meta, blocks, "json"

def _parse_jsonl_document(raw_text: str, source_path: Path) -> Tuple[Metadata, List[Block], str]:

    meta = Metadata(title=f"{source_path.stem.replace('_', ' ').title()} Records")
    blocks: List[Block] = []
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

    items: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            items.append(json.loads(ln))
        except Exception:
            pass

    if items and all(isinstance(x, dict) for x in items):
        headers: List[str] = []
        for x in items:
            for k in x.keys():
                if k not in headers:
                    headers.append(k)
        rows = [[str(x.get(h, "")) for h in headers] for x in items]
        blocks.append(HeadingBlock(level=1, text=f"{meta.title} ({len(items)} items)"))
        blocks.append(TableBlock(headers=headers, rows=rows))
    else:
        blocks.append(HeadingBlock(level=1, text=meta.title))
        blocks.append(CodeBlock(code=raw_text[:5000], language="jsonl"))

    return meta, blocks, "jsonl"

def _parse_yaml_document(raw_text: str, source_path: Path) -> Tuple[Metadata, List[Block], str]:

    meta = Metadata(title=source_path.stem.replace("_", " ").title())
    blocks: List[Block] = []

    try:
        data = yaml.safe_load(raw_text)
    except Exception:
        blocks.append(CodeBlock(code=raw_text, language="yaml"))
        return meta, blocks, "yaml"

    if isinstance(data, dict):
        blocks.append(HeadingBlock(level=1, text=meta.title))
        scalar_keys = [k for k, v in data.items() if not isinstance(v, (dict, list))]
        if scalar_keys:
            rows = [[str(k), str(data[k])] for k in scalar_keys]
            blocks.append(TableBlock(headers=["Configuration Key", "Value"], rows=rows))

        for k, v in data.items():
            if isinstance(v, (dict, list)):
                blocks.append(HeadingBlock(level=2, text=str(k).replace("_", " ").title()))
                blocks.append(CodeBlock(code=yaml.safe_dump(v, sort_keys=False).strip(), language="yaml"))
    elif isinstance(data, list):
        blocks.append(HeadingBlock(level=1, text=f"{meta.title} Items"))
        if data and all(isinstance(x, dict) for x in data):
            headers = []
            for x in data:
                for k in x.keys():
                    if k not in headers:
                        headers.append(k)
            rows = [[str(x.get(h, "")) for h in headers] for x in data]
            blocks.append(TableBlock(headers=headers, rows=rows))
        else:
            blocks.append(ListBlock(ordered=False, items=[str(x) for x in data]))
    else:
        blocks.append(ParagraphBlock(text=str(data)))

    return meta, blocks, "yaml"

def _parse_tabular_document(raw_text: str, source_path: Path, delimiter: str = ",") -> Tuple[Metadata, List[Block], str]:

    meta = Metadata(title=source_path.stem.replace("_", " ").title())
    blocks: List[Block] = []

    reader = csv.reader(raw_text.splitlines(), delimiter=delimiter)
    all_rows = [row for row in reader if row]
    if not all_rows:
        return meta, [ParagraphBlock(text="(Empty spreadsheet data)")], "tabular"

    headers = [col.strip() for col in all_rows[0]]
    data_rows = [[cell.strip() for cell in row] for row in all_rows[1:]]

    blocks.append(HeadingBlock(level=1, text=meta.title))
    blocks.append(ParagraphBlock(text=f"Tabular dataset containing {len(data_rows)} rows and {len(headers)} columns."))
    blocks.append(TableBlock(headers=headers, rows=data_rows, caption=f"Dataset: {source_path.name}"))

    return meta, blocks, "tabular"

def _parse_xml_document(raw_text: str, source_path: Path) -> Tuple[Metadata, List[Block], str]:

    meta = Metadata(title=source_path.stem.replace("_", " ").title())
    blocks: List[Block] = []

    soup = BeautifulSoup(raw_text, "xml")
    root = soup.find()
    if root is None:
        return meta, [ParagraphBlock(text=raw_text)], "xml"

    meta.title = root.name.replace("_", " ").title()
    blocks.append(HeadingBlock(level=1, text=meta.title))

    if root.attrs:
        attr_rows = [[k, str(v)] for k, v in root.attrs.items()]
        blocks.append(TableBlock(headers=["Attribute", "Value"], rows=attr_rows, caption="Root Tag Attributes"))

    children = [c for c in root.children if c.name]
    for ch in children:
        c_text = ch.get_text().strip()
        grand = [g for g in ch.children if g.name]
        if grand:
            blocks.append(HeadingBlock(level=2, text=ch.name.replace("_", " ").title()))
            grand_rows = [[g.name, g.get_text().strip()] for g in grand]
            blocks.append(TableBlock(headers=["Element", "Value"], rows=grand_rows))
        elif c_text:
            blocks.append(HeadingBlock(level=3, text=ch.name.replace("_", " ").title()))
            blocks.append(ParagraphBlock(text=c_text))

    return meta, blocks, "xml"

def _parse_config_document(raw_text: str, source_path: Path) -> Tuple[Metadata, List[Block], str]:

    meta = Metadata(title=f"{source_path.stem.replace('_', ' ').title()} Configuration")
    blocks: List[Block] = []
    blocks.append(HeadingBlock(level=1, text=meta.title))

    ext = source_path.suffix.lower()

    if ext == ".toml":
        try:
            if sys.version_info >= (3, 11):
                import tomllib
                data = tomllib.loads(raw_text)
            else:
                import toml
                data = toml.loads(raw_text)
            for sec, val in data.items():
                blocks.append(HeadingBlock(level=2, text=sec.replace("_", " ").title()))
                if isinstance(val, dict):
                    rows = [[k, str(v)] for k, v in val.items()]
                    blocks.append(TableBlock(headers=["Key", "Value"], rows=rows))
                else:
                    blocks.append(ParagraphBlock(text=f"{sec} = {val}"))
            return meta, blocks, "config"
        except Exception:
            pass

    cp = configparser.ConfigParser()
    try:
        cp.read_string(raw_text)
        sections = cp.sections()
        if sections:
            for sec in sections:
                blocks.append(HeadingBlock(level=2, text=f"[{sec}]"))
                items = list(cp.items(sec))
                if items:
                    blocks.append(TableBlock(headers=["Key", "Value"], rows=[[k, v] for k, v in items]))
            return meta, blocks, "config"
    except Exception:
        pass

    kv_rows: List[List[str]] = []
    for line in raw_text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith(("#", ";")):
            continue
        if "=" in clean:
            k, v = clean.split("=", 1)
            kv_rows.append([k.strip(), v.strip()])
        elif ":" in clean:
            k, v = clean.split(":", 1)
            kv_rows.append([k.strip(), v.strip()])

    if kv_rows:
        blocks.append(TableBlock(headers=["Setting", "Value"], rows=kv_rows))
    else:
        blocks.append(CodeBlock(code=raw_text, language="ini"))

    return meta, blocks, "config"

def process_data(
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
        raise FileNotFoundError(f"Input data file not found: {path}")

    ext = path.suffix.lower()
    raw_content = _read_file_text(path)

    if ext == ".json":
        meta, blocks, src_type = _parse_json_document(raw_content, path)
    elif ext in (".jsonl", ".ndjson"):
        meta, blocks, src_type = _parse_jsonl_document(raw_content, path)
    elif ext in (".yaml", ".yml"):
        meta, blocks, src_type = _parse_yaml_document(raw_content, path)
    elif ext == ".csv":
        meta, blocks, src_type = _parse_tabular_document(raw_content, path, delimiter=",")
    elif ext == ".tsv":
        meta, blocks, src_type = _parse_tabular_document(raw_content, path, delimiter="\t")
    elif ext == ".xml":
        meta, blocks, src_type = _parse_xml_document(raw_content, path)
    elif ext in (".toml", ".ini", ".cfg", ".env"):
        meta, blocks, src_type = _parse_config_document(raw_content, path)
    else:
        meta, blocks, src_type = _parse_json_document(raw_content, path)

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

    target_out_dir = Path(output_dir) if output_dir else Path("output/DATA")
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
