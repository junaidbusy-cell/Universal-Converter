
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString, Tag
import markdownify

from common.models import (
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
    Metadata,
    Document,
)

def extract_metadata(soup: BeautifulSoup, source_path: str = "") -> Metadata:

    meta = Metadata()

    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        meta.title = title_tag.string.strip()

    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        meta.language = html_tag.get("lang").strip()

    meta_dict: Dict[str, str] = {}
    for tag in soup.find_all("meta"):
        name = tag.get("name") or tag.get("property") or tag.get("http-equiv")
        content = tag.get("content")
        if name and content:
            name_clean = name.strip().lower()
            meta_dict[name_clean] = content.strip()

            if name_clean in ("author", "article:author", "dc.creator"):
                meta.author = meta.author or content.strip()
            elif name_clean in ("description", "og:description", "twitter:description"):
                meta.description = meta.description or content.strip()
            elif name_clean in ("date", "article:published_time", "pubdate", "dc.date"):
                meta.date = meta.date or content.strip()
            elif name_clean in ("generator",):
                meta.generator = content.strip()
            elif name_clean in ("og:title", "twitter:title") and not meta.title:
                meta.title = content.strip()

        if tag.get("charset"):
            meta.charset = tag.get("charset").strip()

    meta.meta_tags = meta_dict

    canonical_link = soup.find("link", rel=lambda r: r and "canonical" in r)
    if canonical_link and canonical_link.get("href"):
        meta.canonical_url = canonical_link.get("href").strip()

    return meta

def format_inline_text(element: Tag) -> str:

    try:

        raw_html = "".join(str(c) for c in element.children)
        md = markdownify.markdownify(raw_html, heading_style="ATX", strip=["style", "script"]).strip()

        md = re.sub(r"\s*\n\s*", " ", md)
        return md if md else element.get_text(strip=True)
    except Exception:
        return element.get_text(strip=True)

def extract_table(table_tag: Tag) -> Tuple[TableBlock, Dict[str, Any]]:

    caption_tag = table_tag.find("caption")
    caption = caption_tag.get_text(strip=True) if caption_tag else None

    tr_elements = table_tag.find_all("tr", recursive=False)
    if not tr_elements:

        tr_elements = table_tag.select("thead > tr, tbody > tr, tfoot > tr")

    grid: List[List[Dict[str, Any]]] = []

    occupied: Set[Tuple[int, int]] = set()

    for r_idx, tr in enumerate(tr_elements):
        while len(grid) <= r_idx:
            grid.append([])

        c_idx = 0
        cells = tr.find_all(["th", "td"], recursive=False)

        for cell in cells:

            while (r_idx, c_idx) in occupied:
                c_idx += 1

            try:
                row_span = max(1, int(cell.get("rowspan", 1)))
            except (ValueError, TypeError):
                row_span = 1
            try:
                col_span = max(1, int(cell.get("colspan", 1)))
            except (ValueError, TypeError):
                col_span = 1

            is_header = cell.name == "th" or tr.parent.name == "thead"
            cell_text = cell.get_text(strip=True)

            cell_data = {
                "text": cell_text,
                "is_header": is_header,
                "row_span": row_span,
                "col_span": col_span,
            }

            for r in range(r_idx, r_idx + row_span):
                while len(grid) <= r:
                    grid.append([])
                for c in range(c_idx, c_idx + col_span):
                    occupied.add((r, c))
                    while len(grid[r]) <= c:
                        grid[r].append(None)
                    grid[r][c] = cell_data

            c_idx += col_span

    text_grid: List[List[str]] = []
    headers: List[str] = []
    rows: List[List[str]] = []

    for r_row in grid:
        row_strings = []
        for cell_entry in r_row:
            row_strings.append(cell_entry["text"] if cell_entry else "")
        text_grid.append(row_strings)

    if text_grid:

        has_header_row = any(c and c.get("is_header") for c in grid[0])
        if has_header_row:
            headers = text_grid[0]
            rows = text_grid[1:]
        else:
            headers = [f"Col {i+1}" for i in range(len(text_grid[0]))]
            rows = text_grid

    table_block = TableBlock(
        headers=headers,
        rows=rows,
        caption=caption,
        grid=grid,
    )

    table_dict = {
        "caption": caption,
        "headers": headers,
        "rows": rows,
        "num_rows": len(rows),
        "num_cols": len(headers) if headers else 0,
    }

    return table_block, table_dict

def extract_list(list_tag: Tag) -> ListBlock:

    ordered = list_tag.name == "ol"
    try:
        start = int(list_tag.get("start", 1))
    except (ValueError, TypeError):
        start = 1

    items: List[Any] = []
    for li in list_tag.find_all("li", recursive=False):

        sub_list = li.find(["ul", "ol"], recursive=False)
        item_text = ""

        direct_parts = []
        for child in li.children:
            if child.name not in ("ul", "ol"):
                if isinstance(child, NavigableString):
                    direct_parts.append(str(child))
                elif isinstance(child, Tag):
                    direct_parts.append(child.get_text())
        item_text = " ".join("".join(direct_parts).split())

        if sub_list:
            nested_block = extract_list(sub_list)
            items.append({
                "text": item_text,
                "nested": nested_block.to_dict(),
            })
        else:
            items.append(item_text)

    return ListBlock(ordered=ordered, start=start, items=items)

def extract_math_element(element: Tag) -> Optional[MathBlock]:

    if element.name == "math":

        annotation = element.find("annotation", attrs={"encoding": re.compile(r"tex", re.I)})
        if annotation and annotation.string:
            latex = annotation.string.strip()
            display = element.get("display") == "block"
            return MathBlock(latex=latex, math_type="display" if display else "inline", original_format="mathml", raw=str(element))

        text = element.get_text(separator=" ", strip=True)
        display = element.get("display") == "block"
        return MathBlock(latex=text, math_type="display" if display else "inline", original_format="mathml", raw=str(element))

    if "katex" in element.get("class", []):

        annotation = element.find("annotation", attrs={"encoding": re.compile(r"tex", re.I)})
        if annotation and annotation.string:
            latex = annotation.string.strip()
            display = "katex-display" in element.get("class", []) or element.parent.name in ("div", "p")
            return MathBlock(latex=latex, math_type="display" if display else "inline", original_format="katex", raw=latex)

    if element.name == "script" and element.get("type", "").startswith("math/tex"):
        stype = element.get("type", "")
        latex = element.string.strip() if element.string else ""
        display = "mode=display" in stype
        return MathBlock(latex=latex, math_type="display" if display else "inline", original_format="mathjax", raw=latex)

    return None

def extract_code_element(element: Tag) -> CodeBlock:

    code_text = ""
    lang: Optional[str] = None

    if element.name == "pre":
        code_tag = element.find("code")
        target = code_tag if code_tag else element
        code_text = target.get_text()

        classes = target.get("class", []) + element.get("class", [])
        for c in classes:
            m = re.match(r"^(?:language|lang|highlight)-([a-zA-Z0-9_\+#\-]+)$", str(c), re.IGNORECASE)
            if m:
                lang = m.group(1).lower()
                break
        return CodeBlock(code=code_text, language=lang, inline=False)
    else:

        return CodeBlock(code=element.get_text(), language=None, inline=True)

def extract_image_element(img_tag: Tag, base_url: Optional[str] = None) -> Tuple[ImageBlock, Dict[str, Any]]:

    src = img_tag.get("src", "").strip()
    if base_url and src:
        src = urljoin(base_url, src)

    alt = img_tag.get("alt", "").strip()
    title = img_tag.get("title", "").strip() or None
    width = img_tag.get("width")
    height = img_tag.get("height")

    caption = None
    figure_parent = img_tag.find_parent("figure")
    if figure_parent:
        figcaption = figure_parent.find("figcaption")
        if figcaption:
            caption = figcaption.get_text(strip=True)

    img_block = ImageBlock(
        src=src,
        alt=alt,
        title=title,
        caption=caption,
        width=str(width) if width else None,
        height=str(height) if height else None,
    )

    img_dict = {
        "src": src,
        "alt": alt,
        "title": title,
        "caption": caption,
        "width": width,
        "height": height,
    }

    return img_block, img_dict

def extract_svg_element(svg_tag: Tag) -> Tuple[EmbedBlock, Dict[str, Any]]:

    title_tag = svg_tag.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    if not title:
        title = svg_tag.get("aria-label") or svg_tag.get("title")

    desc_tag = svg_tag.find("desc")
    desc = desc_tag.get_text(strip=True) if desc_tag else None

    figure_parent = svg_tag.find_parent("figure")
    caption = None
    if figure_parent:
        figcaption = figure_parent.find("figcaption")
        if figcaption:
            caption = figcaption.get_text(strip=True)

    labels = [
        re.sub(r"\s+", " ", t.get_text(strip=True))
        for t in svg_tag.find_all("text")
        if t.get_text(strip=True)
    ]

    view_box = svg_tag.get("viewbox") or svg_tag.get("viewBox")
    width = svg_tag.get("width")
    height = svg_tag.get("height")

    main_label = title or caption or "Vector Diagram"
    details = []
    if desc:
        details.append(desc)
    if labels:
        details.append("Labels: " + ", ".join(labels))

    formatted_title = f"{main_label} ({'; '.join(details)})" if details else main_label

    block = EmbedBlock(
        embed_type="svg",
        src=None,
        title=formatted_title,
        extra={
            "title": title or caption,
            "description": desc,
            "labels": labels,
            "viewBox": view_box,
            "width": width,
            "height": height,
        },
    )

    svg_dict = {
        "type": "svg",
        "title": title or caption,
        "description": desc,
        "labels": labels,
        "viewBox": view_box,
        "width": width,
        "height": height,
    }

    return block, svg_dict

def extract_document(
    soup: BeautifulSoup,
    content_root: Tag,
    source_path: str = "",
    base_url: Optional[str] = None,
) -> Document:

    doc = Document(source=source_path, source_type="html")
    doc.metadata = extract_metadata(soup, source_path)
    doc.title = doc.metadata.title or ""

    block_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "ul", "ol", "pre", "blockquote", "iframe", "math", "svg"}

    processed_elements: Set[int] = set()
    processed_images: Set[int] = set()

    for el in content_root.descendants:
        if not isinstance(el, Tag):
            continue

        if id(el) in processed_elements:
            continue

        parent_processed = False
        curr = el.parent
        while curr and curr != content_root:
            if id(curr) in processed_elements:
                parent_processed = True
                break
            curr = curr.parent
        if parent_processed:
            continue

        tag_name = el.name.lower()

        math_block = extract_math_element(el)
        if math_block:
            doc.blocks.append(math_block)
            processed_elements.add(id(el))
            continue

        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            text = el.get_text(strip=True)
            if text:
                doc.blocks.append(HeadingBlock(level=level, text=text))
                if not doc.title and level == 1:
                    doc.title = text
            processed_elements.add(id(el))

        elif tag_name == "p":

            for img in el.find_all("img"):
                if id(img) not in processed_images:
                    _, img_dict = extract_image_element(img, base_url)
                    doc.images.append(img_dict)
                    processed_images.add(id(img))
            text = format_inline_text(el)
            if text:
                doc.blocks.append(ParagraphBlock(text=text))
            processed_elements.add(id(el))

        elif tag_name == "table":
            tbl_block, tbl_dict = extract_table(el)
            doc.blocks.append(tbl_block)
            doc.tables.append(tbl_dict)
            processed_elements.add(id(el))

        elif tag_name in ("ul", "ol"):
            list_block = extract_list(el)
            doc.blocks.append(list_block)
            processed_elements.add(id(el))

        elif tag_name == "pre":
            code_block = extract_code_element(el)
            doc.blocks.append(code_block)
            processed_elements.add(id(el))

        elif tag_name == "blockquote":
            cite = el.get("cite")
            text = el.get_text(strip=True)
            doc.blocks.append(BlockquoteBlock(text=text, citation=cite))
            processed_elements.add(id(el))

        elif tag_name == "img":
            if id(el) not in processed_images:
                img_block, img_dict = extract_image_element(el, base_url)
                doc.blocks.append(img_block)
                doc.images.append(img_dict)
                processed_images.add(id(el))
            processed_elements.add(id(el))

        elif tag_name in ("iframe", "embed"):
            src = el.get("src")
            if base_url and src:
                src = urljoin(base_url, src)
            title = el.get("title")
            doc.blocks.append(EmbedBlock(embed_type=tag_name, src=src, title=title))
            processed_elements.add(id(el))

        elif tag_name == "svg":
            svg_block, svg_dict = extract_svg_element(el)
            doc.blocks.append(svg_block)
            doc.images.append(svg_dict)
            processed_elements.add(id(el))

        elif tag_name in ("div", "section", "article", "aside", "dd", "dt", "address", "figcaption", "header", "footer"):
            has_child_blocks = el.find(list(block_tags)) is not None
            if not has_child_blocks:
                for img in el.find_all("img"):
                    if id(img) not in processed_images:
                        _, img_dict = extract_image_element(img, base_url)
                        doc.images.append(img_dict)
                        processed_images.add(id(img))
                direct_text = format_inline_text(el)
                if direct_text:
                    doc.blocks.append(ParagraphBlock(text=direct_text))
                    processed_elements.add(id(el))

    for a_tag in content_root.find_all("a", href=True):
        href = a_tag["href"].strip()
        if base_url:
            href = urljoin(base_url, href)
        text = a_tag.get_text(strip=True)
        title = a_tag.get("title")
        doc.links.append({
            "href": href,
            "text": text,
            "title": title,
        })

    return doc
