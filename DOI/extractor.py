
import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from lxml import etree
from bs4 import BeautifulSoup

from .models import (
    PaperModel,
    PaperAuthor,
    PaperJournal,
    PaperRights,
    PaperAccess,
    PaperSection,
    PaperTable,
    PaperFigure,
    PaperFormula,
    PaperReference,
    CitationLink,
)

def _clean_text(val: Optional[str]) -> str:
    if not val:
        return ""

    return re.sub(r"\s+", " ", val).strip()

def parse_jats_authors(front_elem: etree._Element) -> List[PaperAuthor]:

    authors: List[PaperAuthor] = []
    aff_map: Dict[str, str] = {}

    for aff in front_elem.findall(".//aff"):
        aff_id = aff.get("id")
        aff_text = _clean_text("".join(aff.itertext()))
        if aff_id:
            aff_map[aff_id] = aff_text

    for contrib in front_elem.findall('.//contrib[@contrib-type="author"]'):
        name_elem = contrib.find("name")
        given = None
        surname = None
        full_name = None

        if name_elem is not None:
            given_el = name_elem.find("given-names")
            sur_el = name_elem.find("surname")
            given = _clean_text(given_el.text) if given_el is not None and given_el.text else None
            surname = _clean_text(sur_el.text) if sur_el is not None and sur_el.text else None
            if given and surname:
                full_name = f"{given} {surname}"
            elif surname:
                full_name = surname
        else:
            string_name = contrib.find("string-name")
            if string_name is not None:
                full_name = _clean_text("".join(string_name.itertext()))

        if not full_name:
            continue

        orcid = None
        orcid_elem = contrib.find('.//contrib-id[@contrib-id-type="orcid"]')
        if orcid_elem is not None and orcid_elem.text:
            orcid = _clean_text(orcid_elem.text)

        affiliations: List[str] = []
        for xref in contrib.findall('.//xref[@ref-type="aff"]'):
            rid = xref.get("rid")
            if rid and rid in aff_map:
                affiliations.append(aff_map[rid])
            elif xref.text:
                affiliations.append(_clean_text(xref.text))

        authors.append(
            PaperAuthor(
                name=full_name,
                given_name=given,
                family_name=surname,
                orcid=orcid,
                affiliations=affiliations,
            )
        )

    return authors

def parse_jats_sections(sec_elems: List[etree._Element], level: int = 1) -> List[PaperSection]:

    sections: List[PaperSection] = []

    for idx, sec in enumerate(sec_elems):
        sec_id = sec.get("id") or f"sec_{level}_{idx + 1}"
        title_el = sec.find("title")
        title = _clean_text("".join(title_el.itertext())) if title_el is not None else f"Section {idx + 1}"

        paragraphs: List[str] = []
        for p in sec.findall("p"):
            p_text = _clean_text("".join(p.itertext()))
            if p_text:
                paragraphs.append(p_text)

        sub_secs = parse_jats_sections(sec.findall("sec"), level=level + 1)

        sections.append(
            PaperSection(
                section_id=sec_id,
                title=title,
                level=level,
                paragraphs=paragraphs,
                subsections=sub_secs,
            )
        )

    return sections

def parse_jats_formula(formula_elem: etree._Element, idx: int) -> PaperFormula:

    form_id = formula_elem.get("id") or f"form_{idx}"
    display = formula_elem.tag == "disp-formula"

    tex_elem = formula_elem.find(".//tex-math")
    if tex_elem is not None and tex_elem.text:
        raw_tex = tex_elem.text.strip().strip("$")
        return PaperFormula(
            formula_id=form_id,
            latex=raw_tex,
            display=display,
            source_format="tex-math",
            original_markup=etree.tostring(formula_elem, encoding="unicode"),
        )

    math_elem = formula_elem.find(".//{http://www.w3.org/1998/Math/MathML}math")
    if math_elem is None:
        math_elem = formula_elem.find(".//math")

    if math_elem is not None:

        annot = math_elem.find('.//{http://www.w3.org/1998/Math/MathML}annotation[@encoding="application/x-tex"]')
        if annot is None:
            annot = math_elem.find('.//annotation[@encoding="application/x-tex"]')
        if annot is not None and annot.text:
            return PaperFormula(
                formula_id=form_id,
                latex=annot.text.strip(),
                display=display,
                source_format="mathml",
                original_markup=etree.tostring(formula_elem, encoding="unicode"),
            )

        approx_text = _clean_text("".join(math_elem.itertext()))
        return PaperFormula(
            formula_id=form_id,
            latex=approx_text,
            display=display,
            source_format="mathml",
            original_markup=etree.tostring(formula_elem, encoding="unicode"),
        )

    raw_text = _clean_text("".join(formula_elem.itertext()))
    return PaperFormula(
        formula_id=form_id,
        latex=raw_text,
        display=display,
        source_format="raw",
        original_markup=etree.tostring(formula_elem, encoding="unicode"),
    )

def parse_cals_table(table_wrap: etree._Element, idx: int) -> PaperTable:

    tbl_id = table_wrap.get("id") or f"tab_{idx}"
    label = _clean_text(table_wrap.findtext("label"))
    caption_p = table_wrap.find("caption/p")
    caption = _clean_text("".join(caption_p.itertext())) if caption_p is not None else None

    headers: List[str] = []
    rows: List[List[str]] = []

    colspec_map: Dict[str, int] = {}
    for col_idx, colspec in enumerate(table_wrap.findall(".//colspec")):
        cname = colspec.get("colname")
        if cname:
            colspec_map[cname] = col_idx

    thead = table_wrap.find(".//thead")
    if thead is not None:
        for r in thead.findall(".//row"):
            hdr_cells = [_clean_text("".join(e.itertext())) for e in r.findall("entry")]
            if hdr_cells:
                headers = hdr_cells
                break

    tbody = table_wrap.find(".//tbody")
    if tbody is not None:
        for r in tbody.findall(".//row"):
            row_cells = [_clean_text("".join(e.itertext())) for e in r.findall("entry")]
            if row_cells:
                rows.append(row_cells)

    if not headers and rows:
        headers = rows[0]
        rows = rows[1:]

    return PaperTable(
        table_id=tbl_id,
        label=label,
        caption=caption,
        headers=headers,
        rows=rows,
    )

def parse_html_table(table_wrap: etree._Element, idx: int) -> PaperTable:

    tbl_id = table_wrap.get("id") or f"tab_{idx}"
    label = _clean_text(table_wrap.findtext("label"))
    caption_p = table_wrap.find("caption/p")
    caption = _clean_text("".join(caption_p.itertext())) if caption_p is not None else None

    headers: List[str] = []
    rows: List[List[str]] = []

    table_el = table_wrap.find(".//table")
    if table_el is not None:

        for th in table_el.findall(".//th"):
            headers.append(_clean_text("".join(th.itertext())))

        for tr in table_el.findall(".//tr"):
            tds = tr.findall(".//td")
            if tds:
                r_cells = [_clean_text("".join(td.itertext())) for td in tds]
                rows.append(r_cells)

    if not headers and rows:
        headers = rows[0]
        rows = rows[1:]

    return PaperTable(
        table_id=tbl_id,
        label=label,
        caption=caption,
        headers=headers,
        rows=rows,
    )

def parse_jats_references(back_elem: Optional[etree._Element]) -> Tuple[List[PaperReference], List[CitationLink]]:

    references: List[PaperReference] = []
    citation_links: List[CitationLink] = []

    if back_elem is None:
        return references, citation_links

    for idx, ref in enumerate(back_elem.findall(".//ref")):
        ref_id = ref.get("id") or f"ref_{idx + 1}"
        title = None
        authors: List[str] = []
        journal = None
        year = None
        doi = None

        t_el = ref.find(".//article-title")
        if t_el is None:
            t_el = ref.find(".//chapter-title")
        if t_el is not None:
            title = _clean_text("".join(t_el.itertext()))

        for name in ref.findall(".//name"):
            sur = _clean_text(name.findtext("surname"))
            giv = _clean_text(name.findtext("given-names"))
            if sur and giv:
                authors.append(f"{giv} {sur}")
            elif sur:
                authors.append(sur)

        s_el = ref.find(".//source")
        if s_el is not None:
            journal = _clean_text("".join(s_el.itertext()))

        y_el = ref.find(".//year")
        if y_el is not None and y_el.text:
            try:
                year = int(re.search(r"\d{4}", y_el.text).group(0))
            except Exception:
                pass

        doi_el = ref.find('.//pub-id[@pub-id-type="doi"]')
        if doi_el is not None and doi_el.text:
            doi = _clean_text(doi_el.text)

        raw_cit = _clean_text("".join(ref.itertext()))

        references.append(
            PaperReference(
                reference_id=ref_id,
                title=title,
                authors=authors,
                journal=journal,
                year=year,
                doi=doi,
                raw_citation=raw_cit,
            )
        )

    return references, citation_links

def extract_jats_xml(xml_content: Union[str, bytes], doi: str) -> PaperModel:

    if isinstance(xml_content, str):
        xml_bytes = xml_content.encode("utf-8")
    else:
        xml_bytes = xml_content

    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(xml_bytes, parser=parser)

    front = root.find(".//front")
    title = ""
    authors: List[PaperAuthor] = []
    journal = PaperJournal()
    publication_year = None
    publication_date = None
    abstract = None
    keywords: List[str] = []
    rights = PaperRights()

    if front is not None:

        t_el = front.find(".//article-title")
        if t_el is not None:
            title = _clean_text("".join(t_el.itertext()))

        authors = parse_jats_authors(front)

        j_el = front.find(".//journal-title")
        if j_el is None:
            j_el = front.find(".//journal-meta/journal-id")
        j_name = _clean_text("".join(j_el.itertext())) if j_el is not None else None
        vol = _clean_text(front.findtext(".//volume"))
        iss = _clean_text(front.findtext(".//issue"))
        fp = _clean_text(front.findtext(".//fpage"))
        lp = _clean_text(front.findtext(".//lpage"))
        pages = f"{fp}-{lp}" if fp and lp else (fp or None)
        pub_name = _clean_text(front.findtext(".//publisher-name"))

        journal = PaperJournal(
            name=j_name,
            volume=vol,
            issue=iss,
            pages=pages,
            publisher=pub_name,
        )

        y_el = front.find(".//pub-date/year")
        if y_el is not None and y_el.text:
            try:
                publication_year = int(re.search(r"\d{4}", y_el.text).group(0))
            except Exception:
                pass
        m_el = front.findtext(".//pub-date/month")
        d_el = front.findtext(".//pub-date/day")
        if publication_year and m_el and d_el:
            publication_date = f"{publication_year:04d}-{int(m_el):02d}-{int(d_el):02d}"

        abs_el = front.find(".//abstract")
        if abs_el is not None:
            abstract = _clean_text("".join(abs_el.itertext()))

        for kwd in front.findall(".//kwd-group/kwd"):
            k_text = _clean_text("".join(kwd.itertext()))
            if k_text:
                keywords.append(k_text)

        lic_el = front.find(".//permissions/license")
        if lic_el is not None:
            rights.license_url = lic_el.get("{http://www.w3.org/1999/xlink}href") or lic_el.get("href")
            rights.access_status = "open_access"

    body = root.find(".//body")
    sections: List[PaperSection] = []
    formulas: List[PaperFormula] = []
    tables: List[PaperTable] = []
    figures: List[PaperFigure] = []

    if body is not None:
        sections = parse_jats_sections(body.findall("sec"))

        if not sections:
            body_ps = [_clean_text("".join(p.itertext())) for p in body.findall("p") if _clean_text("".join(p.itertext()))]
            if body_ps:
                sections.append(
                    PaperSection(
                        section_id="sec_main",
                        title="Main Content",
                        level=1,
                        paragraphs=body_ps,
                    )
                )

        for idx, f_el in enumerate(body.findall(".//disp-formula") + body.findall(".//inline-formula")):
            formulas.append(parse_jats_formula(f_el, idx + 1))

        for idx, tw in enumerate(body.findall(".//table-wrap")):
            if tw.find(".//tgroup") is not None:
                tables.append(parse_cals_table(tw, idx + 1))
            else:
                tables.append(parse_html_table(tw, idx + 1))

        for idx, fig in enumerate(body.findall(".//fig")):
            fig_id = fig.get("id") or f"fig_{idx + 1}"
            label = _clean_text(fig.findtext("label"))
            caption_p = fig.find("caption/p")
            caption = _clean_text("".join(caption_p.itertext())) if caption_p is not None else None
            graphic = fig.find(".//graphic")
            g_url = None
            if graphic is not None:
                g_url = graphic.get("{http://www.w3.org/1999/xlink}href") or graphic.get("href")

            figures.append(
                PaperFigure(
                    figure_id=fig_id,
                    label=label,
                    caption=caption,
                    graphic_url=g_url,
                )
            )

    back = root.find(".//back")
    references, citation_links = parse_jats_references(back)

    if body is not None:
        for idx, xref in enumerate(body.findall('.//xref[@ref-type="bibr"]')):
            rid = xref.get("rid")
            marker = _clean_text(xref.text)
            parent_p = xref.find("..")
            context = _clean_text("".join(parent_p.itertext())) if parent_p is not None else None
            if rid:
                citation_links.append(
                    CitationLink(
                        citation_id=f"cit_{idx + 1}",
                        marker=marker or "[*]",
                        reference_ids=[rid],
                        context=context,
                    )
                )

    access = PaperAccess(
        full_text_status="full_text_available",
        open_access=True,
        license=rights.license_name,
        license_url=rights.license_url,
        version="publishedVersion",
        source_format="jats_xml",
    )

    paper = PaperModel(
        doi=doi,
        title=title or f"Publication {doi}",
        authors=authors,
        journal=journal,
        publication_year=publication_year,
        publication_date=publication_date,
        abstract=abstract,
        keywords=keywords,
        rights=rights,
        access=access,
        sections=sections,
        tables=tables,
        figures=figures,
        formulas=formulas,
        references=references,
        citation_links=citation_links,
    )
    return paper

def extract_from_pdf(
    pdf_path: Union[str, Path],
    doi: str,
    metadata: Dict[str, Any],
    ocr_tier: str = "high",
) -> PaperModel:

    from PDF.pipeline import process_pdf

    pdf_doc = process_pdf(pdf_path, output_format="all", mode="auto", tier=ocr_tier)

    sections: List[PaperSection] = []
    current_sec = PaperSection(section_id="sec_1", title="Introduction", level=1)

    for p in pdf_doc.pages:
        for b in p.blocks:
            if b.type == "heading":
                if current_sec.paragraphs:
                    sections.append(current_sec)
                current_sec = PaperSection(
                    section_id=b.block_id,
                    title=b.text,
                    level=b.extra.get("level", 2),
                )
            elif b.type == "paragraph":
                current_sec.paragraphs.append(b.text)

    if current_sec.paragraphs:
        sections.append(current_sec)

    tables: List[PaperTable] = []
    for p in pdf_doc.pages:
        for t in p.tables:
            tables.append(
                PaperTable(
                    table_id=t.table_id,
                    headers=t.headers,
                    rows=t.rows,
                    caption=t.caption,
                )
            )

    formulas: List[PaperFormula] = []
    for p in pdf_doc.pages:
        for f in p.formulas:
            formulas.append(
                PaperFormula(
                    formula_id=f.formula_id,
                    latex=f.latex,
                    display=f.display,
                    source_format="pdf_ocr" if f.source_method == "ocr" else "pdf_native",
                )
            )

    access = PaperAccess(
        full_text_status="full_text_available",
        open_access=True,
        version="publishedVersion",
        source_format="pdf",
    )

    return PaperModel(
        doi=doi,
        title=metadata.get("title") or pdf_doc.metadata.get("title") or f"Publication {doi}",
        authors=metadata.get("authors", []),
        journal=metadata.get("journal", PaperJournal()),
        publication_year=metadata.get("publication_year"),
        abstract=metadata.get("abstract"),
        access=access,
        sections=sections,
        tables=tables,
        formulas=formulas,
    )

def extract_from_html(
    html_text: str,
    doi: str,
    metadata: Dict[str, Any],
    base_url: Optional[str] = None,
) -> PaperModel:

    from HTML.extractor import extract_document
    from HTML.parser import clean_html

    soup = BeautifulSoup(html_text, "html.parser")
    content_root, _ = clean_html(soup)
    doc = extract_document(soup, content_root, base_url=base_url)

    sections: List[PaperSection] = []
    current_sec = PaperSection(section_id="sec_1", title="Full Text", level=1)

    for block in doc.blocks:
        b_type = getattr(block, "type", "")
        if b_type == "heading":
            if current_sec.paragraphs:
                sections.append(current_sec)
            current_sec = PaperSection(
                section_id=getattr(block, "block_id", f"sec_{len(sections) + 1}"),
                title=getattr(block, "text", ""),
                level=getattr(block, "level", 2),
            )
        elif b_type == "paragraph":
            txt = getattr(block, "text", "").strip()
            if txt:
                current_sec.paragraphs.append(txt)

    if current_sec.paragraphs or not sections:
        sections.append(current_sec)

    tables: List[PaperTable] = []
    for idx, t in enumerate(doc.tables):
        tables.append(
            PaperTable(
                table_id=f"tab_{idx + 1}",
                headers=t.get("headers", []),
                rows=t.get("rows", []),
                caption=t.get("caption"),
            )
        )

    formulas: List[PaperFormula] = []
    for idx, b in enumerate(doc.blocks):
        if getattr(b, "type", "") == "math":
            formulas.append(
                PaperFormula(
                    formula_id=f"form_{idx + 1}",
                    latex=getattr(b, "latex", ""),
                    display=getattr(b, "math_type", "") == "display",
                    source_format="html_math",
                )
            )

    access = PaperAccess(
        full_text_status="full_text_available",
        open_access=True,
        version="publishedVersion",
        source_format="html",
    )

    return PaperModel(
        doi=doi,
        title=metadata.get("title") or doc.metadata.title or f"Publication {doi}",
        authors=metadata.get("authors", []),
        journal=metadata.get("journal", PaperJournal()),
        publication_year=metadata.get("publication_year"),
        publication_date=metadata.get("publication_date"),
        abstract=metadata.get("abstract") or doc.metadata.description,
        keywords=metadata.get("keywords", []),
        access=access,
        sections=sections,
        tables=tables,
        formulas=formulas,
    )

