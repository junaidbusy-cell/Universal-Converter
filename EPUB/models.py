
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union

from common.models import (
    Document,
    Metadata,
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
    _safe_serialize,
)

@dataclass
class NavigationItem:

    title: str
    href: str
    target_path: str
    anchor: Optional[str] = None
    children: List["NavigationItem"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "href": self.href,
            "target_path": self.target_path,
            "anchor": self.anchor,
            "children": [c.to_dict() for c in self.children],
        }

@dataclass
class ManifestItem:

    id: str
    href: str
    full_path: str
    media_type: str
    properties: Optional[str] = None
    fallback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "href": self.href,
            "full_path": self.full_path,
            "media_type": self.media_type,
            "properties": self.properties,
            "fallback": self.fallback,
        }

@dataclass
class SpineItem:

    index: int
    idref: str
    full_path: str
    linear: bool = True
    properties: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "idref": self.idref,
            "full_path": self.full_path,
            "linear": self.linear,
            "properties": self.properties,
        }

@dataclass
class FootnoteItem:

    id: str
    text: str
    number: Optional[str] = None
    chapter_href: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "text": self.text,
            "chapter_href": self.chapter_href,
        }

@dataclass
class ChapterModel:

    id: str
    title: str
    href: str
    full_path: str
    spine_index: int
    linear: bool = True
    blocks: List[Block] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    images: List[Dict[str, Any]] = field(default_factory=list)
    links: List[Dict[str, Any]] = field(default_factory=list)
    footnotes: List[FootnoteItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "href": self.href,
            "full_path": self.full_path,
            "spine_index": self.spine_index,
            "linear": self.linear,
            "blocks": [b.to_dict() for b in self.blocks],
            "tables": _safe_serialize(self.tables),
            "images": _safe_serialize(self.images),
            "links": _safe_serialize(self.links),
            "footnotes": [f.to_dict() for f in self.footnotes],
            "warnings": list(self.warnings),
        }

@dataclass
class BookModel:

    source: str = ""
    title: str = ""
    metadata: Metadata = field(default_factory=Metadata)
    epub_version: str = "3.0"
    page_progression_direction: str = "ltr"
    navigation: List[NavigationItem] = field(default_factory=list)
    manifest: Dict[str, ManifestItem] = field(default_factory=dict)
    spine: List[SpineItem] = field(default_factory=list)
    chapters: List[ChapterModel] = field(default_factory=list)
    cover_image_path: Optional[str] = None
    resources: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def update_stats(self) -> None:

        total_blocks = sum(len(c.blocks) for c in self.chapters)
        total_tables = sum(len(c.tables) for c in self.chapters)
        total_images = sum(len(c.images) for c in self.chapters)
        total_links = sum(len(c.links) for c in self.chapters)
        total_footnotes = sum(len(c.footnotes) for c in self.chapters)

        self.stats.update({
            "chapter_count": len(self.chapters),
            "linear_chapter_count": sum(1 for c in self.chapters if c.linear),
            "spine_item_count": len(self.spine),
            "manifest_item_count": len(self.manifest),
            "total_block_count": total_blocks,
            "total_table_count": total_tables,
            "total_image_count": total_images,
            "total_link_count": total_links,
            "total_footnote_count": total_footnotes,
            "warning_count": len(self.warnings),
        })

    def to_dict(self) -> Dict[str, Any]:

        return {
            "source": self.source,
            "title": self.title,
            "metadata": self.metadata.to_dict(),
            "epub_version": self.epub_version,
            "page_progression_direction": self.page_progression_direction,
            "navigation": [n.to_dict() for n in self.navigation],
            "manifest": {k: v.to_dict() for k, v in self.manifest.items()},
            "spine": [s.to_dict() for s in self.spine],
            "chapters": [c.to_dict() for c in self.chapters],
            "cover_image_path": self.cover_image_path,
            "resources": _safe_serialize(self.resources),
            "stats": dict(self.stats),
            "warnings": list(self.warnings),
        }

    def to_document(self, include_nonlinear: bool = False) -> Document:

        self.update_stats()
        doc = Document(
            schema_version="1.0",
            source=self.source,
            source_type="epub",
            title=self.title or self.metadata.title or "eBook",
            metadata=self.metadata,
        )

        doc.metadata.extra["book"] = self.to_dict()
        doc.metadata.extra["table_of_contents"] = [n.to_dict() for n in self.navigation]
        doc.metadata.extra["epub_version"] = self.epub_version
        doc.metadata.extra["cover_image_path"] = self.cover_image_path

        for w in self.warnings:
            doc.add_warning(w)

        for ch in self.chapters:
            if not ch.linear and not include_nonlinear:
                continue

            for w in ch.warnings:
                doc.add_warning(f"[{ch.title or ch.id}] {w}")

            ch_heading = ch.title or f"Chapter {ch.spine_index + 1}"
            doc.blocks.append(HeadingBlock(level=1, text=ch_heading))

            for b in ch.blocks:
                if isinstance(b, HeadingBlock) and b.level == 1 and b.text.strip().lower() == ch_heading.strip().lower():
                    continue
                doc.blocks.append(b)

            doc.tables.extend(ch.tables)
            doc.images.extend(ch.images)
            doc.links.extend(ch.links)

        doc.update_stats()
        return doc
