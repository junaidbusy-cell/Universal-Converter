
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import docx
from docx.text.paragraph import Paragraph
from docx.table import Table, _Cell
from lxml import etree

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
    EmbedBlock,
)
from .assets import AssetManager, NS_A, NS_R, NS_WP, NS_PIC

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NAMESPACES = {
    "w": NS_W,
    "m": NS_M,
    "r": NS_R,
    "a": NS_A,
    "wp": NS_WP,
    "pic": NS_PIC,
}

def _wrap_format(text: str, prefix: str, suffix: Optional[str] = None) -> str:

    if suffix is None:
        suffix = prefix
    leading = len(text) - len(text.lstrip())
    trailing = len(text) - len(text.rstrip())
    lead_str = text[:leading]
    trail_str = text[len(text) - trailing:] if trailing > 0 else ""
    core = text.strip()
    if not core:
        return text
    return f"{lead_str}{prefix}{core}{suffix}{trail_str}"

def get_paragraph_heading_level(paragraph: Paragraph) -> Optional[int]:

    pPr = paragraph._p.find(f"{{{NS_W}}}pPr")
    if pPr is not None:
        outline = pPr.find(f"{{{NS_W}}}outlineLvl")
        if outline is not None:
            try:
                val = int(outline.attrib.get(f"{{{NS_W}}}val", -1))
                if 0 <= val <= 5:
                    return val + 1
            except (ValueError, TypeError):
                pass

    style_name = (paragraph.style.name or "").strip().lower()
    if style_name == "title":
        return 1
    match = re.match(r"^heading\s*([1-6])$", style_name)
    if match:
        return int(match.group(1))

    return None

def is_list_paragraph(paragraph: Paragraph) -> Tuple[bool, bool, int]:

    pPr = paragraph._p.find(f"{{{NS_W}}}pPr")
    if pPr is not None:
        numPr = pPr.find(f"{{{NS_W}}}numPr")
        if numPr is not None:
            ilvl_elem = numPr.find(f"{{{NS_W}}}ilvl")
            ilvl = 0
            if ilvl_elem is not None:
                try:
                    ilvl = int(ilvl_elem.attrib.get(f"{{{NS_W}}}val", 0))
                except (ValueError, TypeError):
                    ilvl = 0

            style_name = (paragraph.style.name or "").strip().lower()
            is_ordered = "number" in style_name or "ordered" in style_name or "1" in style_name
            return True, is_ordered, ilvl

    style_name = (paragraph.style.name or "").strip().lower()
    if "list" in style_name:
        is_ordered = "number" in style_name or "ordered" in style_name
        return True, is_ordered, 0

    return False, False, 0

def extract_paragraph_runs(
    paragraph: Paragraph,
    doc: docx.Document,
    asset_mgr: AssetManager,
) -> Tuple[str, List[ImageBlock], List[MathBlock], List[Dict[str, Any]]]:

    text_parts: List[str] = []
    images: List[ImageBlock] = []
    math_blocks: List[MathBlock] = []
    links: List[Dict[str, Any]] = []

    for child in paragraph._p.xpath("./w:r | ./w:hyperlink | ./m:oMath | ./m:oMathPara | ./w:drawing"):
        tag = child.tag

        if tag.endswith("hyperlink"):
            rel_id = child.attrib.get(f"{{{NS_R}}}id")
            anchor = child.attrib.get(f"{{{NS_W}}}anchor")
            url = ""
            if rel_id and rel_id in doc.part.rels:
                try:
                    url = doc.part.rels[rel_id].target_ref
                except Exception:
                    url = ""
            elif anchor:
                url = f"#{anchor}"

            link_text = "".join(child.xpath(".//w:t/text()")).strip()
            if link_text:
                if url:
                    text_parts.append(f"[{link_text}]({url})")
                    links.append({"href": url, "text": link_text, "type": "external" if url.startswith("http") else "internal"})
                else:
                    text_parts.append(link_text)

        elif "oMath" in tag:

            math_text = "".join(child.xpath(".//*[local-name()='t']/text()")).strip()
            raw_xml = etree.tostring(child, encoding="unicode")
            is_display = "oMathPara" in tag
            m_block = MathBlock(
                latex=math_text or "[OMML Equation]",
                math_type="display" if is_display else "inline",
                original_format="omml",
                raw=raw_xml,
            )
            math_blocks.append(m_block)
            text_parts.append(f"$${math_text}$$" if is_display else f"${math_text}$")

        elif tag.endswith("drawing"):
            blip = child.xpath(".//a:blip")
            if blip:
                doc_pr = child.xpath(".//wp:docPr")
                extent = child.xpath(".//wp:extent")
                res = asset_mgr.extract_image(
                    blip_elem=blip[0],
                    doc=doc,
                    doc_pr_elem=doc_pr[0] if doc_pr else None,
                    extent_elem=extent[0] if extent else None,
                )
                if res:
                    img_block, _ = res
                    images.append(img_block)
                    text_parts.append(f"![{img_block.alt}]({img_block.src})")

            txbx_runs = child.xpath(".//*[local-name()='txbxContent']//*[local-name()='t']/text()")
            if txbx_runs:
                tb_text = "".join(txbx_runs).strip()
                if tb_text:
                    text_parts.append(tb_text)

        elif tag.endswith("r"):

            blip = child.xpath(".//a:blip")
            if blip:
                doc_pr = child.xpath(".//wp:docPr")
                extent = child.xpath(".//wp:extent")
                res = asset_mgr.extract_image(
                    blip_elem=blip[0],
                    doc=doc,
                    doc_pr_elem=doc_pr[0] if doc_pr else None,
                    extent_elem=extent[0] if extent else None,
                )
                if res:
                    img_block, _ = res
                    images.append(img_block)
                    text_parts.append(f"![{img_block.alt}]({img_block.src})")

            txbx_runs = child.xpath(".//*[local-name()='txbxContent']//*[local-name()='t']/text()")
            if txbx_runs:
                tb_text = "".join(txbx_runs).strip()
                if tb_text:
                    text_parts.append(tb_text)
                    continue

            t_nodes = child.xpath("./w:t")
            if not t_nodes:
                continue
            run_text = "".join(t.text for t in t_nodes if t.text)
            if not run_text:
                continue

            rPr = child.find(f"{{{NS_W}}}rPr")
            is_bold = False
            is_italic = False
            is_underline = False
            is_strike = False
            vert_align = None

            if rPr is not None:
                is_bold = rPr.find(f"{{{NS_W}}}b") is not None
                is_italic = rPr.find(f"{{{NS_W}}}i") is not None
                is_underline = rPr.find(f"{{{NS_W}}}u") is not None
                is_strike = rPr.find(f"{{{NS_W}}}strike") is not None
                vert = rPr.find(f"{{{NS_W}}}vertAlign")
                if vert is not None:
                    vert_align = vert.attrib.get(f"{{{NS_W}}}val")

            formatted = run_text
            if vert_align == "subscript":
                formatted = _wrap_format(formatted, "~")
            elif vert_align == "superscript":
                formatted = _wrap_format(formatted, "^")
            if is_bold:
                formatted = _wrap_format(formatted, "**")
            if is_italic:
                formatted = _wrap_format(formatted, "*")
            if is_underline:
                formatted = _wrap_format(formatted, "<u>", "</u>")
            if is_strike:
                formatted = _wrap_format(formatted, "~~")

            text_parts.append(formatted)

    full_text = "".join(text_parts).strip()
    return full_text, images, math_blocks, links

def extract_table(
    table: Table,
    doc: docx.Document,
    asset_mgr: AssetManager,
) -> Tuple[TableBlock, Dict[str, Any]]:

    rows_data: List[List[Dict[str, Any]]] = []

    occupied: Set[Tuple[int, int]] = set()

    active_vmerges: Dict[int, Dict[str, Any]] = {}

    for r_idx, row in enumerate(table.rows):
        c_idx = 0
        for cell in row.cells:

            while (r_idx, c_idx) in occupied:
                c_idx += 1

            tcPr = cell._tc.find(f"{{{NS_W}}}tcPr")
            col_span = 1
            v_merge_val = None

            if tcPr is not None:

                gridSpan = tcPr.find(f"{{{NS_W}}}gridSpan")
                if gridSpan is not None:
                    try:
                        col_span = max(1, int(gridSpan.attrib.get(f"{{{NS_W}}}val", 1)))
                    except (ValueError, TypeError):
                        col_span = 1

                vMerge = tcPr.find(f"{{{NS_W}}}vMerge")
                if vMerge is not None:
                    v_merge_val = vMerge.attrib.get(f"{{{NS_W}}}val", "continue")

            cell_text_parts = []
            for p in cell.paragraphs:
                p_text, _, _, _ = extract_paragraph_runs(p, doc, asset_mgr)
                if p_text:
                    cell_text_parts.append(p_text)
            cell_text = "\n".join(cell_text_parts).strip()

            if v_merge_val == "continue" and c_idx in active_vmerges:

                origin_cell = active_vmerges[c_idx]
                origin_cell["row_span"] += 1
                for c in range(c_idx, c_idx + col_span):
                    occupied.add((r_idx, c))
                c_idx += col_span
                continue

            cell_dict = {
                "text": cell_text,
                "row": r_idx,
                "col": c_idx,
                "col_span": col_span,
                "row_span": 1,
                "is_header": r_idx == 0,
            }

            if v_merge_val == "restart":
                active_vmerges[c_idx] = cell_dict
            elif c_idx in active_vmerges and v_merge_val is None:
                del active_vmerges[c_idx]

            while len(rows_data) <= r_idx:
                rows_data.append([])

            rows_data[r_idx].append(cell_dict)

            for c in range(c_idx, c_idx + col_span):
                occupied.add((r_idx, c))

            c_idx += col_span

    headers: List[str] = []
    text_rows: List[List[str]] = []

    if rows_data:

        headers = [c["text"] for c in rows_data[0]]
        for r in rows_data[1:]:
            text_rows.append([c["text"] for c in r])

    table_block = TableBlock(
        headers=headers,
        rows=text_rows,
        caption=None,
    )

    table_dict = {
        "headers": headers,
        "rows": text_rows,
        "num_rows": len(text_rows),
        "num_cols": len(headers) if headers else 0,
    }

    return table_block, table_dict

def extract_section_metadata(doc: docx.Document) -> List[Dict[str, Any]]:

    sections_meta: List[Dict[str, Any]] = []

    for idx, section in enumerate(doc.sections):

        orientation = "portrait"
        if section.orientation == docx.enum.section.WD_ORIENT.LANDSCAPE:
            orientation = "landscape"

        header_text = ""
        footer_text = ""
        try:
            if section.header:
                header_text = "\n".join(p.text for p in section.header.paragraphs if p.text.strip())
        except Exception:
            pass

        try:
            if section.footer:
                footer_text = "\n".join(p.text for p in section.footer.paragraphs if p.text.strip())
        except Exception:
            pass

        sec_data = {
            "section_index": idx + 1,
            "orientation": orientation,
            "page_width_inches": round(section.page_width.inches, 2) if section.page_width else None,
            "page_height_inches": round(section.page_height.inches, 2) if section.page_height else None,
            "top_margin_inches": round(section.top_margin.inches, 2) if section.top_margin else None,
            "bottom_margin_inches": round(section.bottom_margin.inches, 2) if section.bottom_margin else None,
            "left_margin_inches": round(section.left_margin.inches, 2) if section.left_margin else None,
            "right_margin_inches": round(section.right_margin.inches, 2) if section.right_margin else None,
            "header": header_text if header_text else None,
            "footer": footer_text if footer_text else None,
            "different_first_page": section.different_first_page_header_footer,
        }
        sections_meta.append(sec_data)

    return sections_meta

def extract_docx_document(
    doc: docx.Document,
    source_path: str = "",
    asset_mgr: Optional[AssetManager] = None,
) -> Document:

    if asset_mgr is None:
        asset_mgr = AssetManager()

    result_doc = Document(source=source_path, source_type="docx")

    sections_meta = extract_section_metadata(doc)
    result_doc.metadata.extra["sections"] = sections_meta

    active_list_items: List[str] = []
    active_list_ordered: bool = False

    def flush_list():
        nonlocal active_list_items, active_list_ordered
        if active_list_items:
            result_doc.blocks.append(ListBlock(
                ordered=active_list_ordered,
                items=list(active_list_items),
            ))
            active_list_items = []

    for block_elem in doc.iter_inner_content():
        if isinstance(block_elem, Paragraph):
            heading_lvl = get_paragraph_heading_level(block_elem)
            is_list, is_ordered, _ = is_list_paragraph(block_elem)
            text, images, math_blocks, links = extract_paragraph_runs(block_elem, doc, asset_mgr)

            for l in links:
                result_doc.links.append(l)
            for img in images:
                result_doc.images.append({
                    "src": img.src,
                    "alt": img.alt,
                    "title": img.title,
                    "width": img.width,
                    "height": img.height,
                    "sha256": img.extra.get("sha256"),
                })

            if is_list and text:
                if active_list_items and active_list_ordered != is_ordered:
                    flush_list()
                active_list_ordered = is_ordered

                clean_item = re.sub(r"^[\*\-\•\d\.]+\s*", "", text)
                active_list_items.append(clean_item if clean_item else text)
                continue
            else:
                flush_list()

            if heading_lvl is not None and text:
                result_doc.blocks.append(HeadingBlock(level=heading_lvl, text=text))
                if not result_doc.title and heading_lvl == 1:
                    result_doc.title = text

            elif math_blocks:
                for mb in math_blocks:
                    result_doc.blocks.append(mb)
                clean_remaining = re.sub(r"\$\$.*?\$\$|\$.*?\$", "", text).strip()
                if clean_remaining:
                    result_doc.blocks.append(ParagraphBlock(text=clean_remaining))

            elif images:
                for img in images:
                    result_doc.blocks.append(img)
                clean_remaining = re.sub(r"!\[.*?\]\(.*?\)", "", text).strip()
                if clean_remaining:
                    result_doc.blocks.append(ParagraphBlock(text=clean_remaining))

            elif text:

                style_name = (block_elem.style.name or "").lower()
                if "code" in style_name or "monospace" in style_name:
                    result_doc.blocks.append(CodeBlock(code=text))
                elif "quote" in style_name:
                    result_doc.blocks.append(BlockquoteBlock(text=text))
                else:
                    result_doc.blocks.append(ParagraphBlock(text=text))

        elif isinstance(block_elem, Table):
            flush_list()
            tbl_block, tbl_dict = extract_table(block_elem, doc, asset_mgr)
            result_doc.blocks.append(tbl_block)
            result_doc.tables.append(tbl_dict)

    flush_list()
    return result_doc
