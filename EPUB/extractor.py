
import re
import warnings
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from bs4 import BeautifulSoup, Tag, NavigableString, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

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
)
from .models import (
    NavigationItem,
    ManifestItem,
    SpineItem,
    FootnoteItem,
    ChapterModel,
    BookModel,
)
from .parser import (
    resolve_epub_path,
    parse_opf_package,
    parse_navigation,
)
from .assets import EPUBAssetManager

BACKLINK_PATTERN = re.compile(r"(\s*(\u21a9|↩|\^|\[return\]|back to text|back)\s*)+$", re.IGNORECASE)

def _clean_text(s: str) -> str:

    if not s:
        return ""
    return " ".join(s.split())

def _extract_mathml(math_el: Tag) -> MathBlock:

    annotation = math_el.find("annotation", attrs={"encoding": re.compile(r"tex", re.I)})
    if annotation and annotation.string:
        latex = annotation.string.strip()
        display = math_el.get("display") == "block"
        return MathBlock(
            latex=latex,
            math_type="display" if display else "inline",
            original_format="mathml",
            raw=str(math_el),
        )

    text = math_el.get_text(separator=" ", strip=True)
    display = math_el.get("display") == "block"
    return MathBlock(
        latex=text,
        math_type="display" if display else "inline",
        original_format="mathml",
        raw=str(math_el),
    )

def _extract_table(table_el: Tag) -> Tuple[List[str], List[List[str]], Optional[str]]:

    try:
        from HTML.extractor import extract_table
        table_block, _ = extract_table(table_el)
        return table_block.headers, table_block.rows, table_block.caption
    except Exception:
        caption_el = table_el.find("caption")
        caption = _clean_text(caption_el.get_text()) if caption_el else None

        headers: List[str] = []

        th_tags = table_el.find_all("th")
        if th_tags:
            headers = [_clean_text(th.get_text()) for th in th_tags]

        rows: List[List[str]] = []
        for tr in table_el.find_all("tr"):
            td_tags = tr.find_all("td")
            if not td_tags:
                continue
            row_vals = [_clean_text(td.get_text()) for td in td_tags]
            rows.append(row_vals)

        if not headers and rows:
            headers = rows[0]
            rows = rows[1:]

        return headers, rows, caption

def _extract_list(list_el: Tag) -> ListBlock:

    is_ordered = (list_el.name == "ol")
    start = 1
    if is_ordered and list_el.get("start"):
        try:
            start = int(list_el.get("start"))
        except ValueError:
            pass

    items: List[Any] = []
    for li in list_el.find_all("li", recursive=False):
        text_parts = []
        nested_block = None
        for child in li.children:
            if isinstance(child, NavigableString):
                text_parts.append(str(child))
            elif isinstance(child, Tag):
                if child.name in ("ol", "ul"):
                    nested_block = _extract_list(child)
                else:
                    text_parts.append(child.get_text())

        li_text = _clean_text("".join(text_parts))
        if nested_block:
            items.append({"text": li_text, "nested": nested_block.to_dict()})
        else:
            items.append(li_text)

    return ListBlock(ordered=is_ordered, start=start, items=items)

def _detect_code_language(el: Tag) -> Optional[str]:

    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    for cls in classes:
        for prefix in ("language-", "lang-", "highlight-"):
            if cls.lower().startswith(prefix):
                return cls[len(prefix):].lower()
    return None

def extract_chapter(
    zf: zipfile.ZipFile,
    spine_item: SpineItem,
    chapter_title_hint: Optional[str] = None,
    asset_mgr: Optional[EPUBAssetManager] = None,
) -> ChapterModel:

    full_path = spine_item.full_path
    warnings: List[str] = []

    if full_path not in set(zf.namelist()):
        warnings.append(f"Chapter file '{full_path}' missing from archive.")
        return ChapterModel(
            id=spine_item.idref,
            title=chapter_title_hint or spine_item.idref,
            href=full_path,
            full_path=full_path,
            spine_index=spine_item.index,
            linear=spine_item.linear,
            warnings=warnings,
        )

    try:
        raw_bytes = zf.read(full_path)
        soup = BeautifulSoup(raw_bytes, "lxml")
    except Exception as e:
        warnings.append(f"Failed to parse XHTML in '{full_path}': {e}")
        return ChapterModel(
            id=spine_item.idref,
            title=chapter_title_hint or spine_item.idref,
            href=full_path,
            full_path=full_path,
            spine_index=spine_item.index,
            linear=spine_item.linear,
            warnings=warnings,
        )

    chapter_title = chapter_title_hint or ""
    if not chapter_title:
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            chapter_title = _clean_text(h1.get_text())
        elif soup.title and soup.title.get_text(strip=True):
            chapter_title = _clean_text(soup.title.get_text())
        else:
            chapter_title = f"Chapter {spine_item.index + 1}"

    blocks: List[Block] = []
    tables_list: List[Dict[str, Any]] = []
    images_list: List[Dict[str, Any]] = []
    links_list: List[Dict[str, Any]] = []
    footnotes_list: List[FootnoteItem] = []

    content_root = soup.body if soup.body else soup

    for script_or_style in content_root.find_all(["script", "style"]):
        script_or_style.decompose()

    footnote_tags = content_root.find_all(
        lambda tag: (
            tag.name in ("aside", "div", "p", "li") and (
                any("footnote" in str(v).lower() or "endnote" in str(v).lower()
                    for v in tag.attrs.values()) or
                (tag.get("id") and "fn" in str(tag.get("id")).lower())
            )
        )
    )

    extracted_footnote_ids: Set[str] = set()
    for fn in footnote_tags:
        fn_id = fn.get("id", "")
        fn_text_raw = fn.get_text(strip=True)

        cleaned_fn_text = BACKLINK_PATTERN.sub("", fn_text_raw).strip()

        if cleaned_fn_text and fn_id:
            footnotes_list.append(FootnoteItem(
                id=fn_id,
                text=cleaned_fn_text,
                chapter_href=full_path,
            ))
            extracted_footnote_ids.add(fn_id)

    for el in content_root.descendants:
        if not isinstance(el, Tag):
            continue

        if el.get("id") in extracted_footnote_ids:
            continue

        tag_name = el.name.lower()

        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            text = _clean_text(el.get_text())
            if text:
                blocks.append(HeadingBlock(level=level, text=text))

        elif tag_name == "p":
            if not el.find_parent(["table", "ul", "ol", "blockquote", "aside"]):
                p_text = _clean_text(el.get_text())
                if p_text:
                    blocks.append(ParagraphBlock(text=p_text))

        elif tag_name in ("ul", "ol"):
            if not el.find_parent(["ul", "ol", "table"]):
                list_block = _extract_list(el)
                if list_block.items:
                    blocks.append(list_block)

        elif tag_name == "table":
            if not el.find_parent("table"):
                headers, rows, caption = _extract_table(el)
                blocks.append(TableBlock(headers=headers, rows=rows, caption=caption))
                tables_list.append({
                    "chapter": full_path,
                    "caption": caption,
                    "headers": headers,
                    "rows": rows,
                })

        elif tag_name == "img":
            src = el.get("src", "").strip()
            alt = el.get("alt", "").strip()
            title = el.get("title", "").strip() or None

            if src:
                resolved_img_path = resolve_epub_path(full_path, src)
                img_dict = None
                if asset_mgr:
                    img_dict = asset_mgr.extract_archive_image(
                        zf=zf,
                        full_path=resolved_img_path,
                        alt_text=alt,
                    )
                out_src = img_dict.get("path") if img_dict else resolved_img_path
                blocks.append(ImageBlock(src=out_src, alt=alt, title=title))
                images_list.append({
                    "chapter": full_path,
                    "src": out_src,
                    "original_path": resolved_img_path,
                    "alt": alt,
                    "title": title,
                })

        elif tag_name == "pre":
            code_el = el.find("code")
            code_text = (code_el or el).get_text()
            lang = _detect_code_language(code_el or el)
            blocks.append(CodeBlock(code=code_text, language=lang))

        elif tag_name == "math":
            math_block = _extract_mathml(el)
            blocks.append(math_block)

        elif tag_name == "blockquote":
            if not el.find_parent("blockquote"):
                q_text = _clean_text(el.get_text())
                if q_text:
                    blocks.append(BlockquoteBlock(text=q_text))

        elif tag_name == "a":
            href = el.get("href", "").strip()
            a_text = _clean_text(el.get_text())
            if href and a_text:
                links_list.append({
                    "chapter": full_path,
                    "text": a_text,
                    "href": href,
                })

    return ChapterModel(
        id=spine_item.idref,
        title=chapter_title,
        href=spine_item.full_path,
        full_path=full_path,
        spine_index=spine_item.index,
        linear=spine_item.linear,
        blocks=blocks,
        tables=tables_list,
        images=images_list,
        links=links_list,
        footnotes=footnotes_list,
        warnings=warnings,
    )

def extract_book(
    zf: zipfile.ZipFile,
    source_path: Union[str, Path],
    asset_mgr: Optional[EPUBAssetManager] = None,
) -> BookModel:

    src_str = str(source_path)

    opf_path = resolve_epub_path("", zf.namelist()[0] if False else "")
    from .parser import get_opf_path
    opf_path = get_opf_path(zf)

    meta, epub_ver, page_prog, manifest, spine, nav_path, ncx_path, cover_path = parse_opf_package(
        zf=zf,
        opf_path=opf_path,
    )

    navigation = parse_navigation(zf=zf, nav_full_path=nav_path, ncx_full_path=ncx_path)

    toc_titles: Dict[str, str] = {}
    def map_toc(nav_items: List[NavigationItem]):
        for item in nav_items:
            if item.target_path and item.title:
                toc_titles[item.target_path] = item.title
            if item.children:
                map_toc(item.children)
    map_toc(navigation)

    extracted_cover_path = None
    if cover_path and asset_mgr:
        cover_dict = asset_mgr.extract_archive_image(
            zf=zf,
            full_path=cover_path,
            alt_text="Cover Image",
            is_cover=True,
        )
        if cover_dict:
            extracted_cover_path = cover_dict.get("path")

    chapters: List[ChapterModel] = []
    for s_item in spine:
        title_hint = toc_titles.get(s_item.full_path)
        ch_model = extract_chapter(
            zf=zf,
            spine_item=s_item,
            chapter_title_hint=title_hint,
            asset_mgr=asset_mgr,
        )
        chapters.append(ch_model)

    resources_list: List[Dict[str, Any]] = []
    for m_item in manifest.values():
        resources_list.append(m_item.to_dict())

    book = BookModel(
        source=src_str,
        title=meta.title or Path(source_path).stem.replace("_", " ").title(),
        metadata=meta,
        epub_version=epub_ver,
        page_progression_direction=page_prog,
        navigation=navigation,
        manifest=manifest,
        spine=spine,
        chapters=chapters,
        cover_image_path=extracted_cover_path,
        resources=resources_list,
    )
    book.update_stats()
    return book
