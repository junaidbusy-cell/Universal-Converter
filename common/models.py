
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Union

def _safe_serialize(val: Any) -> Any:

    if hasattr(val, "to_dict") and callable(val.to_dict):
        return val.to_dict()
    elif isinstance(val, (datetime, date)):
        return val.isoformat()
    elif isinstance(val, dict):
        return {k: _safe_serialize(v) for k, v in val.items()}
    elif isinstance(val, (list, tuple)):
        return [_safe_serialize(v) for v in val]
    elif isinstance(val, set):
        return [_safe_serialize(v) for v in sorted(list(val))]
    return val

@dataclass
class Metadata:

    title: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None
    description: Optional[str] = None
    canonical_url: Optional[str] = None
    charset: Optional[str] = None
    generator: Optional[str] = None
    meta_tags: Dict[str, str] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "author": self.author,
            "date": self.date,
            "language": self.language,
            "description": self.description,
            "canonical_url": self.canonical_url,
            "charset": self.charset,
            "generator": self.generator,
            "meta_tags": dict(self.meta_tags),
            "extra": _safe_serialize(self.extra),
        }

@dataclass
class Block:

    type: str = "block"
    id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"type": self.type}
        if self.id is not None:
            result["id"] = self.id
        for key, val in self.__dict__.items():
            if key not in ("type", "id", "extra"):
                result[key] = _safe_serialize(val)
        if self.extra:
            result["extra"] = _safe_serialize(self.extra)
        return result

@dataclass
class HeadingBlock(Block):

    type: str = "heading"
    level: int = 1
    text: str = ""

@dataclass
class ParagraphBlock(Block):

    type: str = "paragraph"
    text: str = ""
    raw_html: Optional[str] = None

@dataclass
class ListBlock(Block):

    type: str = "list"
    ordered: bool = False
    start: int = 1
    items: List[Any] = field(default_factory=list)

@dataclass
class TableBlock(Block):

    type: str = "table"
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    caption: Optional[str] = None
    grid: Optional[List[List[Dict[str, Any]]]] = None

@dataclass
class ImageBlock(Block):

    type: str = "image"
    src: str = ""
    alt: str = ""
    title: Optional[str] = None
    caption: Optional[str] = None
    width: Optional[str] = None
    height: Optional[str] = None

@dataclass
class LinkBlock(Block):

    type: str = "link"
    href: str = ""
    text: str = ""
    title: Optional[str] = None

@dataclass
class CodeBlock(Block):

    type: str = "code"
    code: str = ""
    language: Optional[str] = None
    inline: bool = False

@dataclass
class MathBlock(Block):

    type: str = "math"
    latex: str = ""
    math_type: str = "display"
    original_format: str = "raw"
    raw: Optional[str] = None

@dataclass
class BlockquoteBlock(Block):

    type: str = "blockquote"
    text: str = ""
    citation: Optional[str] = None

@dataclass
class EmbedBlock(Block):

    type: str = "embed"
    embed_type: str = "iframe"
    src: Optional[str] = None
    title: Optional[str] = None

@dataclass
class Document:

    schema_version: str = "1.0"
    source: str = ""
    source_type: str = "html"
    title: str = ""
    text: str = ""
    markdown: str = ""
    metadata: Metadata = field(default_factory=Metadata)
    blocks: List[Block] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_warning(self, message: str) -> None:

        if message not in self.warnings:
            self.warnings.append(message)

    def update_stats(self) -> None:

        self.stats.update({
            "character_count": len(self.text),
            "word_count": len(self.text.split()) if self.text else 0,
            "block_count": len(self.blocks),
            "table_count": len(self.tables),
            "image_count": len(self.images),
            "link_count": len(self.links),
            "chunk_count": len(self.chunks),
            "warning_count": len(self.warnings),
        })

    def to_dict(self) -> Dict[str, Any]:

        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "source_type": self.source_type,
            "title": self.title,
            "text": self.text,
            "markdown": self.markdown,
            "metadata": self.metadata.to_dict(),
            "blocks": [b.to_dict() for b in self.blocks],
            "tables": _safe_serialize(self.tables),
            "images": _safe_serialize(self.images),
            "links": _safe_serialize(self.links),
            "chunks": _safe_serialize(self.chunks),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }
