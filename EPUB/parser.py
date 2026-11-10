
import os
import posixpath
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from lxml import etree

from common.models import Metadata
from .models import NavigationItem, ManifestItem, SpineItem

SUPPORTED_EXTENSIONS = {".epub"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0

class EPUBError(Exception):

    pass

class UnsupportedEPUBError(EPUBError):

    pass

class CorruptEPUBError(EPUBError):

    pass

class EncryptedEPUBError(EPUBError):

    pass

def resolve_epub_path(base_file_path: str, relative_href: str) -> str:

    clean_href = relative_href.split("#")[0].split("?")[0].strip()
    if not clean_href:
        return base_file_path

    base_dir = posixpath.dirname(base_file_path)
    target = posixpath.normpath(posixpath.join(base_dir, clean_href))

    if target.startswith("../") or target.startswith("/"):
        raise CorruptEPUBError(f"Directory traversal attempt detected in EPUB archive: '{relative_href}'")

    return target

def validate_epub_package(file_path: Union[str, Path]) -> zipfile.ZipFile:

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if not path.is_file():
        raise UnsupportedEPUBError(f"Target is not a regular file: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedEPUBError(
            f"Unsupported file extension '{ext}'. Only {sorted(SUPPORTED_EXTENSIONS)} are supported."
        )

    file_size = path.stat().st_size
    if file_size == 0:
        raise CorruptEPUBError(f"File is empty (0 bytes): {path}")

    if file_size > MAX_FILE_SIZE_BYTES:
        raise UnsupportedEPUBError(
            f"File size {file_size} bytes exceeds maximum limit ({MAX_FILE_SIZE_BYTES} bytes)."
        )

    try:
        zf = zipfile.ZipFile(path, "r")
        namelist = set(zf.namelist())

        if "META-INF/container.xml" not in namelist:
            zf.close()
            raise CorruptEPUBError(f"Missing required 'META-INF/container.xml' in {path.name}")

        if "mimetype" in namelist:
            mimetype_bytes = zf.read("mimetype").strip()
            if mimetype_bytes != b"application/epub+zip":
                zf.close()
                raise CorruptEPUBError(
                    f"Invalid mimetype '{mimetype_bytes.decode('ascii', errors='replace')}'; expected 'application/epub+zip'"
                )

        if "META-INF/rights.xml" in namelist:
            zf.close()
            raise EncryptedEPUBError(f"Publication '{path.name}' contains DRM encryption (rights.xml); decryption is unsupported.")

        total_uncompressed = 0
        for info in zf.infolist():
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                zf.close()
                raise UnsupportedEPUBError(
                    f"Uncompressed archive size exceeds limit ({MAX_UNCOMPRESSED_BYTES} bytes)."
                )

        if file_size > 0 and (total_uncompressed / file_size) > MAX_COMPRESSION_RATIO:
            zf.close()
            raise UnsupportedEPUBError("Archive exhibits suspicious compression ratio exceeding safety threshold.")

        return zf

    except zipfile.BadZipFile as e:
        raise CorruptEPUBError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

def get_opf_path(zf: zipfile.ZipFile) -> str:

    try:
        container_bytes = zf.read("META-INF/container.xml")
        root = etree.fromstring(container_bytes)
        rootfile_elems = root.xpath("//*[local-name()='rootfile']")
        if not rootfile_elems:
            raise CorruptEPUBError("Missing <rootfile> element in META-INF/container.xml")

        full_path = rootfile_elems[0].attrib.get("full-path", "").strip()
        if not full_path:
            raise CorruptEPUBError("Empty 'full-path' attribute in META-INF/container.xml")

        if full_path not in set(zf.namelist()):
            raise CorruptEPUBError(f"Referenced OPF file '{full_path}' does not exist in EPUB archive.")

        return full_path
    except etree.XMLSyntaxError as e:
        raise CorruptEPUBError(f"Malformed XML in META-INF/container.xml: {e}")

def parse_opf_package(
    zf: zipfile.ZipFile,
    opf_path: str,
) -> Tuple[Metadata, str, str, Dict[str, ManifestItem], List[SpineItem], Optional[str], Optional[str], Optional[str]]:

    try:
        opf_bytes = zf.read(opf_path)
        root = etree.fromstring(opf_bytes)
    except Exception as e:
        raise CorruptEPUBError(f"Failed to read or parse OPF file '{opf_path}': {e}")

    epub_version = root.attrib.get("version", "3.0").strip()

    meta = Metadata()
    creators_list: List[str] = []

    titles = root.xpath("//*[local-name()='metadata']/*[local-name()='title']/text()")
    if titles:
        meta.title = str(titles[0]).strip()

    creators = root.xpath("//*[local-name()='metadata']/*[local-name()='creator']/text()")
    for c in creators:
        c_str = str(c).strip()
        if c_str:
            creators_list.append(c_str)
    if creators_list:
        meta.author = ", ".join(creators_list)

    descriptions = root.xpath("//*[local-name()='metadata']/*[local-name()='description']/text()")
    if descriptions:
        meta.description = str(descriptions[0]).strip()

    languages = root.xpath("//*[local-name()='metadata']/*[local-name()='language']/text()")
    if languages:
        meta.language = str(languages[0]).strip()

    dates = root.xpath("//*[local-name()='metadata']/*[local-name()='date']/text()")
    if dates:
        meta.date = str(dates[0]).strip()

    extra: Dict[str, Any] = {"creators": creators_list}
    publishers = root.xpath("//*[local-name()='metadata']/*[local-name()='publisher']/text()")
    if publishers:
        extra["publisher"] = str(publishers[0]).strip()
    rights = root.xpath("//*[local-name()='metadata']/*[local-name()='rights']/text()")
    if rights:
        extra["rights"] = str(rights[0]).strip()
    identifiers = root.xpath("//*[local-name()='metadata']/*[local-name()='identifier']/text()")
    if identifiers:
        extra["identifier"] = str(identifiers[0]).strip()

    meta.extra = extra

    manifest: Dict[str, ManifestItem] = {}
    nav_item_id = None
    ncx_item_id = None
    cover_item_id = None

    legacy_covers = root.xpath("//*[local-name()='metadata']/*[local-name()='meta'][@name='cover']/@content")
    if legacy_covers:
        cover_item_id = str(legacy_covers[0]).strip()

    for item_elem in root.xpath("//*[local-name()='manifest']/*[local-name()='item']"):
        i_id = item_elem.attrib.get("id", "").strip()
        i_href = item_elem.attrib.get("href", "").strip()
        i_media = item_elem.attrib.get("media-type", "").strip()
        i_props = item_elem.attrib.get("properties", "").strip() or None
        i_fallback = item_elem.attrib.get("fallback", "").strip() or None

        if not i_id or not i_href:
            continue

        full_path = resolve_epub_path(opf_path, i_href)
        manifest_item = ManifestItem(
            id=i_id,
            href=i_href,
            full_path=full_path,
            media_type=i_media,
            properties=i_props,
            fallback=i_fallback,
        )
        manifest[i_id] = manifest_item

        if i_props and "nav" in i_props.split():
            nav_item_id = i_id

        if i_media == "application/x-dtbncx+xml":
            ncx_item_id = i_id

        if i_props and "cover-image" in i_props.split():
            cover_item_id = i_id

    spine_elems = root.xpath("//*[local-name()='spine']")
    page_progression = "ltr"
    spine_ncx_id = None

    if spine_elems:
        page_progression = spine_elems[0].attrib.get("page-progression-direction", "ltr").strip() or "ltr"
        spine_ncx_id = spine_elems[0].attrib.get("toc", "").strip() or None

    if spine_ncx_id and not ncx_item_id and spine_ncx_id in manifest:
        ncx_item_id = spine_ncx_id

    spine: List[SpineItem] = []
    for s_idx, itemref in enumerate(root.xpath("//*[local-name()='spine']/*[local-name()='itemref']")):
        idref = itemref.attrib.get("idref", "").strip()
        linear_val = itemref.attrib.get("linear", "yes").strip().lower()
        linear = (linear_val != "no")
        s_props = itemref.attrib.get("properties", "").strip() or None

        man_item = manifest.get(idref)
        full_path = man_item.full_path if man_item else ""

        spine.append(SpineItem(
            index=s_idx,
            idref=idref,
            full_path=full_path,
            linear=linear,
            properties=s_props,
        ))

    nav_full_path = manifest[nav_item_id].full_path if nav_item_id and nav_item_id in manifest else None
    ncx_full_path = manifest[ncx_item_id].full_path if ncx_item_id and ncx_item_id in manifest else None
    cover_full_path = manifest[cover_item_id].full_path if cover_item_id and cover_item_id in manifest else None

    return meta, epub_version, page_progression, manifest, spine, nav_full_path, ncx_full_path, cover_full_path

def _parse_epub3_nav_ol(ol_elem: etree._Element, nav_path: str) -> List[NavigationItem]:

    items: List[NavigationItem] = []

    for li in ol_elem.xpath("./*[local-name()='li']"):

        link_elem = li.xpath("./*[local-name()='a']")
        span_elem = li.xpath("./*[local-name()='span']")

        title = ""
        href = ""
        target_path = ""
        anchor = None

        if link_elem:
            title = "".join(link_elem[0].itertext()).strip()
            href = link_elem[0].attrib.get("href", "").strip()
            if href:
                parts = href.split("#", 1)
                anchor = parts[1] if len(parts) > 1 else None
                target_path = resolve_epub_path(nav_path, parts[0])
        elif span_elem:
            title = "".join(span_elem[0].itertext()).strip()

        children: List[NavigationItem] = []
        child_ols = li.xpath("./*[local-name()='ol']")
        if child_ols:
            children = _parse_epub3_nav_ol(child_ols[0], nav_path)

        if title or href:
            items.append(NavigationItem(
                title=title or "Untitled Section",
                href=href,
                target_path=target_path,
                anchor=anchor,
                children=children,
            ))

    return items

def parse_epub3_nav(zf: zipfile.ZipFile, nav_path: str) -> List[NavigationItem]:

    try:
        nav_bytes = zf.read(nav_path)
        root = etree.fromstring(nav_bytes)

        nav_nodes = root.xpath("//*[local-name()='nav']")
        toc_nav = None
        for n in nav_nodes:

            attrs = {k.lower(): v for k, v in n.attrib.items()}
            for attr_name, attr_val in attrs.items():
                if "type" in attr_name and "toc" in attr_val.lower():
                    toc_nav = n
                    break
            if toc_nav is not None:
                break

        if toc_nav is None and nav_nodes:
            toc_nav = nav_nodes[0]

        if toc_nav is None:
            return []

        ols = toc_nav.xpath(".//*[local-name()='ol']")
        if not ols:
            return []

        return _parse_epub3_nav_ol(ols[0], nav_path)
    except Exception:
        return []

def _parse_ncx_navpoints(navpoint_elems: List[etree._Element], ncx_path: str) -> List[NavigationItem]:

    items: List[NavigationItem] = []

    for np in navpoint_elems:

        label_text = np.xpath("./*[local-name()='navLabel']/*[local-name()='text']/text()")
        title = str(label_text[0]).strip() if label_text else "Untitled"

        content_src = np.xpath("./*[local-name()='content']/@src")
        href = str(content_src[0]).strip() if content_src else ""

        target_path = ""
        anchor = None
        if href:
            parts = href.split("#", 1)
            anchor = parts[1] if len(parts) > 1 else None
            target_path = resolve_epub_path(ncx_path, parts[0])

        child_navpoints = np.xpath("./*[local-name()='navPoint']")
        children = _parse_ncx_navpoints(child_navpoints, ncx_path)

        items.append(NavigationItem(
            title=title,
            href=href,
            target_path=target_path,
            anchor=anchor,
            children=children,
        ))

    return items

def parse_epub2_ncx(zf: zipfile.ZipFile, ncx_path: str) -> List[NavigationItem]:

    try:
        ncx_bytes = zf.read(ncx_path)
        root = etree.fromstring(ncx_bytes)
        top_navpoints = root.xpath("//*[local-name()='navMap']/*[local-name()='navPoint']")
        return _parse_ncx_navpoints(top_navpoints, ncx_path)
    except Exception:
        return []

def parse_navigation(
    zf: zipfile.ZipFile,
    nav_full_path: Optional[str] = None,
    ncx_full_path: Optional[str] = None,
) -> List[NavigationItem]:

    if nav_full_path and nav_full_path in set(zf.namelist()):
        nav_items = parse_epub3_nav(zf, nav_full_path)
        if nav_items:
            return nav_items

    if ncx_full_path and ncx_full_path in set(zf.namelist()):
        ncx_items = parse_epub2_ncx(zf, ncx_full_path)
        if ncx_items:
            return ncx_items

    return []
