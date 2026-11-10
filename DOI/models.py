
from dataclasses import dataclass, field, asdict
from pathlib import Path
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
class PaperAuthor:

    name: str
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    orcid: Optional[str] = None
    affiliations: List[str] = field(default_factory=list)
    email: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "given_name": self.given_name,
            "family_name": self.family_name,
            "orcid": self.orcid,
            "affiliations": list(self.affiliations),
            "email": self.email,
        }

@dataclass
class PaperJournal:

    name: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    issn: Optional[str] = None
    publisher: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "issn": self.issn,
            "publisher": self.publisher,
        }

@dataclass
class PaperRights:

    license_name: Optional[str] = None
    license_url: Optional[str] = None
    access_status: str = "open_access"
    reuse_permission: str = "unknown"
    attribution_required: bool = True
    terms_checked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "license_name": self.license_name,
            "license_url": self.license_url,
            "access_status": self.access_status,
            "reuse_permission": self.reuse_permission,
            "attribution_required": self.attribution_required,
            "terms_checked": self.terms_checked,
        }

@dataclass
class PaperAccess:

    full_text_status: str = "metadata_only"

    open_access: bool = False
    license: Optional[str] = None
    license_url: Optional[str] = None
    version: str = "unknown"
    source_url: Optional[str] = None
    source_format: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "full_text_status": self.full_text_status,
            "open_access": self.open_access,
            "license": self.license,
            "license_url": self.license_url,
            "version": self.version,
            "source_url": self.source_url,
            "source_format": self.source_format,
        }

@dataclass
class PaperRetrieval:

    metadata_sources: List[str] = field(default_factory=list)
    selected_source: Optional[str] = None
    source_format: Optional[str] = None
    source_hash: Optional[str] = None
    retrieved_at: Optional[str] = None
    raw_file_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata_sources": list(self.metadata_sources),
            "selected_source": self.selected_source,
            "source_format": self.source_format,
            "source_hash": self.source_hash,
            "retrieved_at": self.retrieved_at,
            "raw_file_path": self.raw_file_path,
        }

@dataclass
class PaperSection:

    section_id: str
    title: str
    level: int = 1
    paragraphs: List[str] = field(default_factory=list)
    subsections: List["PaperSection"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "title": self.title,
            "level": self.level,
            "paragraphs": list(self.paragraphs),
            "subsections": [s.to_dict() for s in self.subsections],
        }

@dataclass
class PaperTable:

    table_id: str
    label: Optional[str] = None
    caption: Optional[str] = None
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    footnotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "label": self.label,
            "caption": self.caption,
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
            "footnotes": list(self.footnotes),
        }

@dataclass
class PaperFigure:

    figure_id: str
    label: Optional[str] = None
    caption: Optional[str] = None
    graphic_url: Optional[str] = None
    graphic_path: Optional[str] = None
    alt_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "label": self.label,
            "caption": self.caption,
            "graphic_url": self.graphic_url,
            "graphic_path": self.graphic_path,
            "alt_text": self.alt_text,
        }

@dataclass
class PaperFormula:

    formula_id: str
    latex: str
    display: bool = True
    source_format: str = "tex-math"
    original_markup: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formula_id": self.formula_id,
            "latex": self.latex,
            "display": self.display,
            "source_format": self.source_format,
            "original_markup": self.original_markup,
        }

@dataclass
class PaperReference:

    reference_id: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    raw_citation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "title": self.title,
            "authors": list(self.authors),
            "journal": self.journal,
            "year": self.year,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "doi": self.doi,
            "url": self.url,
            "raw_citation": self.raw_citation,
        }

@dataclass
class CitationLink:

    citation_id: str
    marker: str
    reference_ids: List[str] = field(default_factory=list)
    context: Optional[str] = None
    section: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "marker": self.marker,
            "reference_ids": list(self.reference_ids),
            "context": self.context,
            "section": self.section,
        }

@dataclass
class PaperModel:

    doi: str
    title: str = ""
    authors: List[PaperAuthor] = field(default_factory=list)
    journal: PaperJournal = field(default_factory=PaperJournal)
    publication_year: Optional[int] = None
    publication_date: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    identifiers: Dict[str, str] = field(default_factory=dict)
    article_type: str = "journal-article"
    rights: PaperRights = field(default_factory=PaperRights)
    access: PaperAccess = field(default_factory=PaperAccess)
    retrieval: PaperRetrieval = field(default_factory=PaperRetrieval)
    sections: List[PaperSection] = field(default_factory=list)
    tables: List[PaperTable] = field(default_factory=list)
    figures: List[PaperFigure] = field(default_factory=list)
    formulas: List[PaperFormula] = field(default_factory=list)
    references: List[PaperReference] = field(default_factory=list)
    citation_links: List[CitationLink] = field(default_factory=list)
    supplementary_materials: List[Dict[str, Any]] = field(default_factory=list)
    is_retracted: bool = False
    retraction_notices: List[str] = field(default_factory=list)
    text: str = ""
    markdown: str = ""
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def count_all_sections(self) -> int:
        count = 0
        def _walk(secs: List[PaperSection]):
            nonlocal count
            for s in secs:
                count += 1
                _walk(s.subsections)
        _walk(self.sections)
        return count

    def update_stats(self) -> None:
        word_count = len(self.text.split()) if self.text else 0
        self.stats = {
            "character_count": len(self.text),
            "word_count": word_count,
            "section_count": self.count_all_sections(),
            "table_count": len(self.tables),
            "figure_count": len(self.figures),
            "formula_count": len(self.formulas),
            "reference_count": len(self.references),
            "citation_link_count": len(self.citation_links),
            "chunk_count": len(self.chunks),
            "warning_count": len(self.warnings),
            "full_text_status": self.access.full_text_status,
            "version": self.access.version,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "1.0",
            "source": self.doi,
            "source_type": "doi",
            "metadata": {
                "doi": self.doi,
                "title": self.title,
                "authors": [a.to_dict() for a in self.authors],
                "journal": self.journal.to_dict(),
                "publication_year": self.publication_year,
                "publication_date": self.publication_date,
                "abstract": self.abstract,
                "keywords": list(self.keywords),
                "identifiers": dict(self.identifiers),
                "article_type": self.article_type,
            },
            "rights": self.rights.to_dict(),
            "access": self.access.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "content": {
                "sections": [s.to_dict() for s in self.sections],
                "tables": [t.to_dict() for t in self.tables],
                "figures": [f.to_dict() for f in self.figures],
                "formulas": [fm.to_dict() for fm in self.formulas],
            },
            "references": [r.to_dict() for r in self.references],
            "citation_links": [c.to_dict() for c in self.citation_links],
            "supplementary_materials": _safe_serialize(self.supplementary_materials),
            "publication_status": {
                "is_retracted": self.is_retracted,
                "retraction_notices": list(self.retraction_notices),
            },
            "text": self.text,
            "markdown": self.markdown,
            "chunks": _safe_serialize(self.chunks),
            "warnings": list(self.warnings),
            "stats": dict(self.stats),
        }

    def to_document(self) -> Document:

        author_names = [a.name for a in self.authors]
        primary_author = author_names[0] if author_names else None

        meta = Metadata(
            title=self.title or f"Paper {self.doi}",
            author=primary_author,
            date=self.publication_date or (str(self.publication_year) if self.publication_year else None),
            description=self.abstract,
            extra={
                "doi": self.doi,
                "journal": self.journal.to_dict(),
                "authors": [a.to_dict() for a in self.authors],
                "rights": self.rights.to_dict(),
                "access": self.access.to_dict(),
                "retrieval": self.retrieval.to_dict(),
                "is_retracted": self.is_retracted,
                "identifiers": dict(self.identifiers),
            },
        )

        doc_blocks: List[Block] = []

        if self.abstract:
            doc_blocks.append(HeadingBlock(id="h_abstract", level=2, text="Abstract"))
            doc_blocks.append(ParagraphBlock(id="p_abstract", text=self.abstract))

        block_counter = 1
        def _flatten_sections(secs: List[PaperSection]):
            nonlocal block_counter
            for s in secs:
                doc_blocks.append(HeadingBlock(
                    id=s.section_id or f"sec_{block_counter}",
                    level=min(6, max(1, s.level)),
                    text=s.title,
                ))
                block_counter += 1
                for p_text in s.paragraphs:
                    doc_blocks.append(ParagraphBlock(
                        id=f"p_{block_counter}",
                        text=p_text,
                    ))
                    block_counter += 1
                _flatten_sections(s.subsections)

        _flatten_sections(self.sections)

        for fm in self.formulas:
            doc_blocks.append(MathBlock(
                id=fm.formula_id,
                latex=fm.latex,
                math_type="display" if fm.display else "inline",
                original_format=fm.source_format,
            ))

        doc_tables: List[Dict[str, Any]] = []
        for t in self.tables:
            doc_blocks.append(TableBlock(
                id=t.table_id,
                headers=list(t.headers),
                rows=[list(r) for r in t.rows],
                caption=f"{t.label}: {t.caption}" if t.label and t.caption else (t.caption or t.label),
            ))
            doc_tables.append(t.to_dict())

        doc_images: List[Dict[str, Any]] = []
        for fig in self.figures:
            doc_blocks.append(ImageBlock(
                id=fig.figure_id,
                src=fig.graphic_path or fig.graphic_url or "",
                alt=fig.alt_text or fig.label or "Figure",
                caption=f"{fig.label}: {fig.caption}" if fig.label and fig.caption else (fig.caption or fig.label),
            ))
            doc_images.append(fig.to_dict())

        if self.references:
            doc_blocks.append(HeadingBlock(id="h_refs", level=2, text="References"))
            for r in self.references:
                ref_txt = r.raw_citation or f"{', '.join(r.authors)} ({r.year or 'n.d.'}). {r.title or 'Untitled'}."
                doc_blocks.append(ParagraphBlock(id=f"ref_{r.reference_id}", text=ref_txt))

        doc_links: List[Dict[str, Any]] = [
            {"href": f"https://doi.org/{self.doi}", "text": self.doi}
        ]
        for r in self.references:
            if r.doi:
                doc_links.append({"href": f"https://doi.org/{r.doi}", "text": r.doi})

        unified_doc = Document(
            schema_version="1.0",
            source=self.doi,
            source_type="doi",
            title=meta.title,
            text=self.text,
            markdown=self.markdown,
            metadata=meta,
            blocks=doc_blocks,
            tables=doc_tables,
            images=doc_images,
            links=doc_links,
            chunks=list(self.chunks),
            warnings=list(self.warnings),
            stats=dict(self.stats),
        )
        unified_doc.update_stats()
        return unified_doc
