
import json
from typing import Any, Dict, List, Optional
import yaml

from .models import PaperModel, PaperSection, PaperTable, PaperFormula, PaperFigure, PaperReference

def _escape_table_cell(text: str) -> str:

    if not text:
        return ""
    clean = text.replace("\n", " ").replace("\r", "")
    return clean.replace("|", "\\|").strip()

def export_markdown(paper: PaperModel, include_frontmatter: bool = True) -> str:

    parts: List[str] = []

    if include_frontmatter:
        author_names = [a.name for a in paper.authors]
        fm_data: Dict[str, Any] = {
            "source_type": "doi",
            "doi": paper.doi,
            "title": paper.title,
            "authors": author_names,
            "journal": paper.journal.name if paper.journal else None,
            "publication_year": paper.publication_year,
            "version": paper.access.version,
            "access_status": paper.access.full_text_status,
            "open_access": paper.access.open_access,
        }
        if paper.is_retracted:
            fm_data["retracted"] = True

        cleaned_fm = {k: v for k, v in fm_data.items() if v is not None}
        fm_yaml = yaml.safe_dump(cleaned_fm, sort_keys=False, allow_unicode=True).strip()
        parts.append(f"---\n{fm_yaml}\n---")
        parts.append("")

    if paper.is_retracted:
        parts.append("> [!CAUTION]")
        parts.append("> **RETRACTION NOTICE**: This publication has been retracted by the publisher or authors.")
        for n in paper.retraction_notices:
            parts.append(f"> - {n}")
        parts.append("")

    parts.append(f"# {paper.title}\n")

    if paper.authors:
        author_lines: List[str] = []
        for a in paper.authors:
            aff_str = f" ({', '.join(a.affiliations)})" if a.affiliations else ""
            orcid_str = f" [ORCID: {a.orcid}]" if a.orcid else ""
            author_lines.append(f"- **{a.name}**{aff_str}{orcid_str}")
        parts.append("## Authors\n")
        parts.append("\n".join(author_lines) + "\n")

    if paper.abstract:
        parts.append("## Abstract\n")
        parts.append(f"{paper.abstract}\n")

    ref_id_to_num: Dict[str, int] = {r.reference_id: idx + 1 for idx, r in enumerate(paper.references)}

    def _render_paragraph(text: str) -> str:

        linked = text
        for r_id, num in ref_id_to_num.items():

            linked = linked.replace(f"[{r_id}]", f"[[{num}]](#ref-{num})")
        return linked

    def _render_sections(secs: List[PaperSection]):
        for s in secs:
            prefix = "#" * min(6, max(2, s.level + 1))
            parts.append(f"{prefix} {s.title}\n")
            for p in s.paragraphs:
                parts.append(f"{_render_paragraph(p)}\n")
            _render_sections(s.subsections)

    _render_sections(paper.sections)

    if paper.formulas:
        for f in paper.formulas:
            if f.display:
                parts.append(f"$$\n{f.latex}\n$$\n")
            else:
                parts.append(f"${f.latex}$\n")

    for t in paper.tables:
        t_title = f"{t.label}: {t.caption}" if t.label and t.caption else (t.caption or t.label or "Table")
        parts.append(f"### {t_title}\n")
        headers = t.headers if t.headers else [f"Col {i+1}" for i in range(len(t.rows[0]))] if t.rows else []
        if headers:
            hdr_line = "| " + " | ".join(_escape_table_cell(h) for h in headers) + " |"
            sep_line = "| " + " | ".join("---" for _ in headers) + " |"
            row_lines = []
            for r in t.rows:
                padded = list(r) + [""] * max(0, len(headers) - len(r))
                row_lines.append("| " + " | ".join(_escape_table_cell(c) for c in padded[:len(headers)]) + " |")
            parts.append("\n".join([hdr_line, sep_line] + row_lines) + "\n")

    for fig in paper.figures:
        fig_title = f"{fig.label}: {fig.caption}" if fig.label and fig.caption else (fig.caption or fig.label or "Figure")
        g_path = fig.graphic_path or fig.graphic_url or ""
        parts.append(f"![{fig_title}]({g_path})\n")
        parts.append(f"*{fig_title}*\n")

    if paper.references:
        parts.append("## References\n")
        for idx, r in enumerate(paper.references):
            num = idx + 1
            author_str = ", ".join(r.authors) if r.authors else "Unknown Authors"
            year_str = f"({r.year})" if r.year else "(n.d.)"
            title_str = f"{r.title}." if r.title else ""
            journal_str = f"*{r.journal}*." if r.journal else ""
            doi_link = f" [https://doi.org/{r.doi}](https://doi.org/{r.doi})" if r.doi else ""

            parts.append(f'<a id="ref-{num}"></a>[{num}] {author_str} {year_str} {title_str} {journal_str}{doi_link}\n')

    return "\n".join(parts).strip() + "\n"

def export_text(paper: PaperModel) -> str:

    lines: List[str] = []

    banner = "=" * 60
    lines.append(banner)
    lines.append(paper.title.upper())
    lines.append(banner)
    lines.append(f"DOI: {paper.doi}")
    if paper.authors:
        lines.append(f"Authors: {', '.join(a.name for a in paper.authors)}")
    if paper.journal.name:
        lines.append(f"Journal: {paper.journal.name}")
    if paper.publication_year:
        lines.append(f"Year: {paper.publication_year}")
    lines.append("")

    if paper.abstract:
        lines.append(banner)
        lines.append("ABSTRACT")
        lines.append(banner)
        lines.append(paper.abstract)
        lines.append("")

    def _render_sections_txt(secs: List[PaperSection]):
        for s in secs:
            lines.append(banner)
            lines.append(s.title.upper())
            lines.append(banner)
            for p in s.paragraphs:
                lines.append(p)
                lines.append("")
            _render_sections_txt(s.subsections)

    _render_sections_txt(paper.sections)

    if paper.tables:
        for t in paper.tables:
            t_title = f"{t.label}: {t.caption}" if t.label and t.caption else (t.caption or t.label or "Table")
            lines.append(f"--- {t_title} ---")
            if t.headers:
                lines.append("  |  ".join(t.headers))
                lines.append("-" * 40)
            for r in t.rows:
                lines.append("  |  ".join(r))
            lines.append("")

    if paper.formulas:
        for f in paper.formulas:
            lines.append(f"[Formula: {f.latex}]")
            lines.append("")

    if paper.references:
        lines.append(banner)
        lines.append("REFERENCES")
        lines.append(banner)
        for idx, r in enumerate(paper.references):
            author_str = ", ".join(r.authors) if r.authors else "Unknown Authors"
            year_str = f"({r.year})" if r.year else "(n.d.)"
            title_str = f"{r.title}." if r.title else ""
            lines.append(f"[{idx + 1}] {author_str} {year_str} {title_str}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"

def export_json(paper: PaperModel, indent: int = 2) -> str:

    return json.dumps(paper.to_dict(), indent=indent, ensure_ascii=False)
