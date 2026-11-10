
import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from bs4 import BeautifulSoup, Tag, NavigableString
from lxml import etree
import trafilatura

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
)
from .fetcher import FetchResult

def _clean_text(s: str) -> str:

    if not s:
        return ""
    return " ".join(s.split())

def resolve_url(base_url: str, relative_url: str) -> str:

    if not relative_url:
        return base_url
    return urllib.parse.urljoin(base_url, relative_url.strip())

def extract_webpage_metadata(soup: BeautifulSoup, fetch_result: FetchResult) -> Metadata:

    meta = Metadata()
    extra: Dict[str, Any] = {}
    sources: Dict[str, str] = {}
    json_ld_records: List[Dict[str, Any]] = []

    final_url = fetch_result.final_url
    parsed_url = urllib.parse.urlparse(final_url)
    site_name = parsed_url.hostname or ""

    for script_tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw_text = script_tag.string or script_tag.get_text()
            if not raw_text:
                continue
            data = json.loads(raw_text.strip())

            items: List[Dict[str, Any]] = []
            if isinstance(data, list):
                items.extend(data)
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    items.extend(data["@graph"])
                else:
                    items.append(data)

            for item in items:
                if not isinstance(item, dict):
                    continue
                json_ld_records.append(item)

                hl = item.get("headline") or item.get("name")
                if hl and not meta.title:
                    meta.title = _clean_text(str(hl))
                    sources["title"] = "json-ld"

                desc = item.get("description")
                if desc and not meta.description:
                    meta.description = _clean_text(str(desc))
                    sources["description"] = "json-ld"

                author_val = item.get("author")
                if author_val and not meta.author:
                    if isinstance(author_val, dict):
                        meta.author = _clean_text(str(author_val.get("name", "")))
                    elif isinstance(author_val, list) and author_val:
                        first = author_val[0]
                        meta.author = _clean_text(first.get("name", "") if isinstance(first, dict) else str(first))
                    elif isinstance(author_val, str):
                        meta.author = _clean_text(author_val)
                    if meta.author:
                        sources["author"] = "json-ld"

                date_pub = item.get("datePublished") or item.get("dateCreated")
                if date_pub and not meta.date:
                    meta.date = str(date_pub).strip()
                    sources["date"] = "json-ld"
        except Exception:
            pass

    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        extra["og:title"] = _clean_text(og_title["content"])
        if not meta.title:
            meta.title = extra["og:title"]
            sources["title"] = "og:title"

    og_desc = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    if og_desc and og_desc.get("content"):
        content_desc = _clean_text(og_desc["content"])
        extra["og:description"] = content_desc
        if not meta.description:
            meta.description = content_desc
            sources["description"] = og_desc.get("property") or og_desc.get("name")

    og_author = soup.find("meta", attrs={"property": "article:author"}) or soup.find("meta", attrs={"name": "author"})
    if og_author and og_author.get("content"):
        content_auth = _clean_text(og_author["content"])
        if not meta.author:
            meta.author = content_auth
            sources["author"] = og_author.get("property") or og_author.get("name")

    og_time = soup.find("meta", attrs={"property": "article:published_time"})
    if og_time and og_time.get("content") and not meta.date:
        meta.date = str(og_time["content"]).strip()
        sources["date"] = "article:published_time"

    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    if og_site and og_site.get("content"):
        site_name = _clean_text(og_site["content"])

    og_image = soup.find("meta", attrs={"property": "og:image"})
    if og_image and og_image.get("content"):
        extra["og:image"] = resolve_url(final_url, og_image["content"])

    og_type = soup.find("meta", attrs={"property": "og:type"})
    if og_type and og_type.get("content"):
        extra["og:type"] = _clean_text(og_type["content"])

    tw_card = soup.find("meta", attrs={"name": "twitter:card"})
    if tw_card and tw_card.get("content"):
        extra["twitter:card"] = _clean_text(tw_card["content"])

    tw_image = soup.find("meta", attrs={"name": "twitter:image"})
    if tw_image and tw_image.get("content"):
        extra["twitter:image"] = resolve_url(final_url, tw_image["content"])

    meta_keywords = soup.find("meta", attrs={"name": "keywords"})
    if meta_keywords and meta_keywords.get("content"):
        keywords_str = meta_keywords["content"]
        meta.keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    if canonical_tag and canonical_tag.get("href"):
        meta.canonical_url = resolve_url(final_url, canonical_tag["href"])

    if not meta.title and soup.title and soup.title.get_text(strip=True):
        meta.title = _clean_text(soup.title.get_text())
        sources["title"] = "<title>"

    if not meta.title:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            meta.title = _clean_text(h1.get_text())
            sources["title"] = "<h1>"

    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        meta.language = str(html_tag["lang"]).strip()

    extra["site_name"] = site_name
    extra["json_ld"] = json_ld_records
    extra["metadata_sources"] = sources
    meta.extra = extra

    return meta

def _parse_trafilatura_xml(
    xml_str: str,
    base_url: str,
) -> Tuple[List[Block], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:

    blocks: List[Block] = []
    tables: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    links: List[Dict[str, Any]] = []

    try:
        root = etree.fromstring(xml_str.encode("utf-8"))
    except Exception:
        return blocks, tables, images, links

    main_elem = root.find("main")
    if main_elem is None:
        main_elem = root

    def _extract_inline_links_and_images(element: Any):

        for g in element.iter("graphic"):
            src = g.attrib.get("src", "").strip()
            if src:
                abs_src = resolve_url(base_url, src)
                alt = g.attrib.get("alt", "")
                title = g.attrib.get("title", "")
                images.append({"src": abs_src, "alt": alt, "title": title})

        for r in element.iter("ref"):
            target = r.attrib.get("target") or r.attrib.get("href")
            if target:
                abs_href = resolve_url(base_url, target.strip())
                txt = _clean_text("".join(r.itertext()))
                links.append({"href": abs_href, "text": txt})

    for elem in main_elem:
        tag = elem.tag.lower()

        if tag == "head":
            rend = elem.attrib.get("rend", "h2").lower()
            level = 2
            if rend.startswith("h") and rend[1:].isdigit():
                level = max(1, min(6, int(rend[1:])))
            text = _clean_text("".join(elem.itertext()))
            if text:
                blocks.append(HeadingBlock(level=level, text=text))
            _extract_inline_links_and_images(elem)

        elif tag == "p":
            text = _clean_text("".join(elem.itertext()))
            if text:
                blocks.append(ParagraphBlock(text=text))
            _extract_inline_links_and_images(elem)

        elif tag == "list":
            is_ordered = (elem.attrib.get("rend", "") == "ol")
            items = [_clean_text("".join(item.itertext())) for item in elem.findall("item")]
            items = [itm for itm in items if itm]
            if items:
                blocks.append(ListBlock(ordered=is_ordered, items=items))
            _extract_inline_links_and_images(elem)

        elif tag == "table":
            headers: List[str] = []
            rows: List[List[str]] = []
            for row in elem.findall("row"):
                cells = [_clean_text("".join(c.itertext())) for c in row.findall("cell")]
                roles = [c.attrib.get("role", "") for c in row.findall("cell")]
                if any(r == "head" for r in roles) and not headers:
                    headers = cells
                else:
                    rows.append(cells)
            if not headers and rows:
                headers = rows[0]
                rows = rows[1:]
            blocks.append(TableBlock(headers=headers, rows=rows))
            tables.append({
                "headers": headers,
                "rows": rows,
            })
            _extract_inline_links_and_images(elem)

        elif tag in ("graphic", "img", "image"):
            src = elem.attrib.get("src", "").strip()
            if src:
                abs_src = resolve_url(base_url, src)
                alt = elem.attrib.get("alt", "")
                title = elem.attrib.get("title", "")
                blocks.append(ImageBlock(src=abs_src, alt=alt, title=title))
                images.append({"src": abs_src, "alt": alt, "title": title})

        elif tag in ("ref", "a"):
            target = elem.attrib.get("target") or elem.attrib.get("href")
            if target:
                abs_href = resolve_url(base_url, target.strip())
                txt = _clean_text("".join(elem.itertext()))
                blocks.append(LinkBlock(href=abs_href, text=txt))
                links.append({"href": abs_href, "text": txt})

        elif tag == "quote":
            q_text = _clean_text("".join(elem.itertext()))
            if q_text:
                blocks.append(BlockquoteBlock(text=q_text))
            _extract_inline_links_and_images(elem)

        elif tag in ("code", "code-block"):
            c_text = "".join(elem.itertext())
            if c_text.strip():
                blocks.append(CodeBlock(code=c_text))

    return blocks, tables, images, links

def _extract_full_page_blocks(
    soup: BeautifulSoup,
    base_url: str,
) -> Tuple[List[Block], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:

    blocks: List[Block] = []
    tables: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    links: List[Dict[str, Any]] = []

    content_root = soup.body if soup.body else soup
    processed_elements: Set[int] = set()

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
        el_classes = el.get("class", [])
        if isinstance(el_classes, str):
            el_classes = el_classes.split()

        if tag_name == "math":
            latex = el.get_text(separator=" ", strip=True)
            math_type = "display" if el.get("display") == "block" else "inline"
            blocks.append(MathBlock(latex=latex, math_type=math_type))
            processed_elements.add(id(el))
            continue
        elif any(cls in ("math-display", "math", "katex-display") for cls in el_classes):
            latex = el.get_text(strip=True).strip("$")
            math_type = "display" if ("math-display" in el_classes or "katex-display" in el_classes) else "inline"
            blocks.append(MathBlock(latex=latex, math_type=math_type))
            processed_elements.add(id(el))
            continue

        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = int(tag_name[1])
            t = _clean_text(el.get_text())
            if t:
                blocks.append(HeadingBlock(level=lvl, text=t))
            processed_elements.add(id(el))

        elif tag_name == "p":
            p_text = _clean_text(el.get_text())
            if p_text:
                blocks.append(ParagraphBlock(text=p_text))

            for a_tag in el.find_all("a", href=True):
                abs_href = resolve_url(base_url, a_tag["href"].strip())
                txt = _clean_text(a_tag.get_text())
                links.append({"href": abs_href, "text": txt})

            for img_tag in el.find_all("img"):
                src = img_tag.get("src", "").strip()
                if src:
                    abs_src = resolve_url(base_url, src)
                    alt = img_tag.get("alt", "").strip()
                    images.append({"src": abs_src, "alt": alt})
            processed_elements.add(id(el))

        elif tag_name in ("ul", "ol"):
            is_ordered = (tag_name == "ol")
            items = [_clean_text(li.get_text()) for li in el.find_all("li", recursive=False)]
            items = [i for i in items if i]
            if items:
                blocks.append(ListBlock(ordered=is_ordered, items=items))
            processed_elements.add(id(el))

        elif tag_name == "table":
            headers = []
            th_tags = el.find_all("th")
            if th_tags:
                headers = [_clean_text(th.get_text()) for th in th_tags]
            rows = []
            for tr in el.find_all("tr"):
                tds = tr.find_all("td")
                if tds:
                    rows.append([_clean_text(td.get_text()) for td in tds])
            if not headers and rows:
                headers = rows[0]
                rows = rows[1:]
            blocks.append(TableBlock(headers=headers, rows=rows))
            tables.append({"headers": headers, "rows": rows})
            processed_elements.add(id(el))

        elif tag_name == "pre":
            code_text = el.get_text()

            code_tag = el.find("code")
            lang = None
            classes_to_check = list(el_classes)
            if code_tag:
                c_classes = code_tag.get("class", [])
                if isinstance(c_classes, str):
                    c_classes = c_classes.split()
                classes_to_check.extend(c_classes)
            for cls in classes_to_check:
                if cls.startswith("language-") or cls.startswith("lang-"):
                    lang = cls.split("-", 1)[1]
                    break

            if code_text.strip():
                blocks.append(CodeBlock(code=code_text, language=lang))
            processed_elements.add(id(el))

        elif tag_name == "blockquote":
            q_text = _clean_text(el.get_text())
            if q_text:
                blocks.append(BlockquoteBlock(text=q_text))
            processed_elements.add(id(el))

        elif tag_name == "img":
            src = el.get("src", "").strip()
            alt = el.get("alt", "").strip()
            title = el.get("title", "").strip()
            if src:
                abs_src = resolve_url(base_url, src)
                blocks.append(ImageBlock(src=abs_src, alt=alt, title=title))
                images.append({"src": abs_src, "alt": alt, "title": title})
            processed_elements.add(id(el))

        elif tag_name == "a":
            href = el.get("href", "").strip()
            a_text = _clean_text(el.get_text())
            if href:
                abs_href = resolve_url(base_url, href)
                blocks.append(LinkBlock(href=abs_href, text=a_text))
                links.append({"href": abs_href, "text": a_text})
            processed_elements.add(id(el))

    return blocks, tables, images, links

def extract_webpage_document(
    fetch_result: FetchResult,
    mode: str = "article",
    base_url: Optional[str] = None,
) -> Document:

    html_text = fetch_result.text
    final_url = fetch_result.final_url

    soup = BeautifulSoup(html_text, "lxml")

    base_tag = soup.find("base", attrs={"href": True})
    effective_base_url = resolve_url(final_url, base_tag["href"]) if base_tag else final_url
    if base_url:
        effective_base_url = resolve_url(base_url, base_tag["href"]) if base_tag else base_url

    meta = extract_webpage_metadata(soup, fetch_result)
    title = meta.title or "Webpage Document"

    blocks: List[Block] = []
    tables: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    links: List[Dict[str, Any]] = []
    engine_used = "trafilatura"
    fallback_used = False

    if mode.lower() == "article":
        try:
            xml_output = trafilatura.extract(
                html_text,
                url=final_url,
                output_format="xml",
                with_metadata=True,
                include_tables=True,
                include_links=True,
                include_images=True,
                include_formatting=True,
            )
            if xml_output:
                b, t, img, lnk = _parse_trafilatura_xml(xml_output, effective_base_url)

                extracted_char_count = sum(len(x.text) for x in b if hasattr(x, "text"))
                if extracted_char_count >= 50 and len(b) > 0:
                    blocks, tables, images, links = b, t, img, lnk
                else:

                    fallback_used = True
            else:
                fallback_used = True
        except Exception:
            fallback_used = True

    if mode.lower() == "full_page" or fallback_used:
        engine_used = "beautifulsoup"
        blocks, tables, images, links = _extract_full_page_blocks(soup, effective_base_url)

    doc = Document(
        schema_version="1.0",
        source=final_url,
        source_type="webpage",
        title=title,
        metadata=meta,
        blocks=blocks,
        tables=tables,
        images=images,
        links=links,
    )

    doc.metadata.extra["fetch_info"] = fetch_result.to_dict()
    doc.metadata.extra["extraction"] = {
        "mode": mode,
        "engine": engine_used,
        "fallback_used": fallback_used,
    }

    if fallback_used:
        doc.add_warning("Article extractor returned sparse content; fell back to full-page DOM extraction.")

    doc.update_stats()
    return doc
