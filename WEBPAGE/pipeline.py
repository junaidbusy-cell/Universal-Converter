
import hashlib
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

from .fetcher import (
    DEFAULT_TIMEOUT,
    MAX_BODY_BYTES,
    FetchResult,
    fetch_webpage,
    is_safe_url,
    WebpageError,
)
from .extractor import extract_webpage_document
from common.models import Document, ImageBlock
from common.exporters import export_markdown, export_text, export_json
from common.chunker import chunk_document
from common.validator import validate_extraction, validate_output_files, validate_consistency

def generate_output_path(url: str, base_out_dir: Path) -> Tuple[Path, str]:

    parsed = urllib.parse.urlparse(url)
    raw_host = parsed.hostname or "unknown_domain"
    domain = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", raw_host).strip("_")
    if not domain:
        domain = "unknown_domain"

    raw_path = parsed.path.strip("/")
    if raw_path:

        path_stem = Path(raw_path).stem
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", path_stem).strip("_")

        slug = slug[:50]
    else:
        slug = "index"

    if not slug:
        slug = "index"

    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    folder_name = f"{slug}_{url_hash}"
    doc_out_dir = base_out_dir / domain / folder_name

    return doc_out_dir, folder_name

def _download_assets(
    doc: Document,
    doc_out_dir: Path,
    timeout: float = 10.0,
    max_bytes: int = 10 * 1024 * 1024,
    allow_local: bool = False,
    client: Optional[httpx.Client] = None,
) -> int:

    assets_dir = doc_out_dir / "assets"
    downloaded_count = 0
    hash_cache: Dict[str, str] = {}

    image_urls: List[str] = []
    for img_dict in doc.images:
        src = img_dict.get("src", "").strip()
        if src and src not in image_urls:
            image_urls.append(src)

    for block in doc.blocks:
        if isinstance(block, ImageBlock) and block.src.strip():
            src = block.src.strip()
            if src not in image_urls:
                image_urls.append(src)

    if not image_urls:
        return 0

    should_close_client = False
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=5.0, pool=5.0),
            follow_redirects=True,
            verify=True,
        )
        should_close_client = True

    try:
        img_counter = 1
        for img_url in image_urls:

            parsed = urllib.parse.urlparse(img_url)
            if parsed.scheme.lower() not in ("http", "https"):
                continue

            safe, reason = is_safe_url(img_url, allow_local=allow_local)
            if not safe:
                doc.add_warning(f"Skipping asset download for unsafe URL '{img_url}': {reason}")
                continue

            try:
                response = client.get(img_url)
                if response.status_code != 200:
                    doc.add_warning(f"Failed to download asset '{img_url}': HTTP {response.status_code}")
                    continue

                body = response.content
                if len(body) > max_bytes:
                    doc.add_warning(f"Asset '{img_url}' exceeded maximum size ({len(body)} > {max_bytes} bytes).")
                    continue

                if not body:
                    continue

                sha256 = hashlib.sha256(body).hexdigest()
                if sha256 in hash_cache:
                    rel_path = hash_cache[sha256]
                else:
                    assets_dir.mkdir(parents=True, exist_ok=True)
                    ext = Path(parsed.path).suffix.lower()
                    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
                        content_type = response.headers.get("Content-Type", "").lower()
                        if "jpeg" in content_type:
                            ext = ".jpg"
                        elif "png" in content_type:
                            ext = ".png"
                        elif "webp" in content_type:
                            ext = ".webp"
                        elif "gif" in content_type:
                            ext = ".gif"
                        elif "svg" in content_type:
                            ext = ".svg"
                        else:
                            ext = ".png"
                    elif ext == ".jpeg":
                        ext = ".jpg"

                    filename = f"image_{img_counter:03d}{ext}"
                    img_counter += 1
                    target_file = assets_dir / filename
                    target_file.write_bytes(body)
                    rel_path = f"assets/{filename}"
                    hash_cache[sha256] = rel_path
                    downloaded_count += 1

                for img_dict in doc.images:
                    if img_dict.get("src") == img_url:
                        img_dict["local_path"] = str(assets_dir / Path(rel_path).name)
                        img_dict["relative_path"] = rel_path

                for block in doc.blocks:
                    if isinstance(block, ImageBlock) and block.src == img_url:
                        block.src = rel_path

            except Exception as e:
                doc.add_warning(f"Error downloading asset '{img_url}': {e}")

    finally:
        if should_close_client:
            client.close()

    return downloaded_count

def process_webpage(
    url: str,
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    mode: str = "article",
    download_assets: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BODY_BYTES,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    run_validation: bool = True,
    force: bool = False,
    client: Optional[httpx.Client] = None,
    allow_local: bool = False,
) -> Document:

    start_time = time.time()

    fetch_result: FetchResult = fetch_webpage(
        url=url,
        timeout=timeout,
        max_bytes=max_bytes,
        allow_local=allow_local,
        client=client,
    )

    doc: Document = extract_webpage_document(
        fetch_result=fetch_result,
        mode=mode,
        base_url=fetch_result.final_url,
    )

    target_out_dir = Path(output_dir) if output_dir else Path("output/WEBPAGE")
    doc_out_dir, file_stem = generate_output_path(fetch_result.final_url, target_out_dir)
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    if download_assets:
        downloaded = _download_assets(
            doc=doc,
            doc_out_dir=doc_out_dir,
            timeout=timeout,
            allow_local=allow_local,
            client=client,
        )
        doc.stats["assets_downloaded"] = downloaded

    txt_content = export_text(doc)
    doc.text = txt_content

    md_content = export_markdown(doc, include_frontmatter=True)
    doc.markdown = md_content

    if enable_chunking:
        doc.chunks = chunk_document(
            doc,
            target_tokens=chunk_size,
            overlap_tokens=chunk_overlap,
        )

    elapsed = time.time() - start_time
    doc.update_stats()
    doc.stats["processing_time_seconds"] = round(elapsed, 4)
    doc.stats["status_code"] = fetch_result.status_code
    doc.stats["content_type"] = fetch_result.content_type
    doc.stats["content_length_bytes"] = len(fetch_result.content_bytes)

    json_content = export_json(doc, indent=2)

    if run_validation:
        is_valid, val_errors = validate_extraction(doc)
        for err in val_errors:
            doc.add_warning(f"Validation notice: {err}")

    target_format = output_format.lower()
    files_to_write: List[Tuple[str, Path, str]] = []

    if target_format in ("md", "all"):
        files_to_write.append(("md", doc_out_dir / f"{file_stem}.md", md_content))
    if target_format in ("txt", "all"):
        files_to_write.append(("txt", doc_out_dir / f"{file_stem}.txt", txt_content))
    if target_format in ("json", "all"):
        files_to_write.append(("json", doc_out_dir / f"{file_stem}.json", json_content))

    written_paths: List[Path] = []
    for fmt_label, out_file, data_str in files_to_write:
        if out_file.exists() and not force:
            written_paths.append(out_file)
            continue
        out_file.write_text(data_str, encoding="utf-8")
        written_paths.append(out_file)

    if run_validation and written_paths:
        has_content = len(doc.blocks) > 0 or len(fetch_result.content_bytes) > 0
        file_valid, file_errors = validate_output_files(written_paths, expect_content=has_content)
        for ferr in file_errors:
            doc.add_warning(f"Output file verification notice: {ferr}")

        cons_valid, cons_errors = validate_consistency(doc, md_content, txt_content, json_content)
        for cerr in cons_errors:
            doc.add_warning(f"Consistency notice: {cerr}")

    return doc
