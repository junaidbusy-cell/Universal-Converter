
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import httpx

from .models import (
    PaperModel,
    PaperAuthor,
    PaperJournal,
    PaperRights,
    PaperAccess,
    PaperRetrieval,
    PaperSection,
)
from .resolver import (
    normalize_doi,
    is_valid_doi,
    fetch_crossref_metadata,
    fetch_datacite_metadata,
    fetch_openalex_metadata,
    consolidate_metadata,
)
from .discovery import (
    query_unpaywall,
    query_europe_pmc,
    discover_candidates,
    rank_and_select_candidate,
    DiscoveryCandidate,
)
from .fetcher import download_paper, PaperDownloadError
from .extractor import extract_jats_xml, extract_from_pdf
from .exporters import export_markdown, export_text, export_json

from common.models import Document
from common.chunker import chunk_document
from common.validator import validate_extraction, validate_output_files, validate_consistency

def doi_to_slug(doi: str) -> str:

    clean = normalize_doi(doi)
    return re.sub(r'[\\/:*?"<>|]', "_", clean)

def process_doi(
    doi: str,
    output_format: str = "all",
    output_dir: Optional[Union[str, Path]] = None,
    metadata_only: bool = False,
    access_mode: str = "open",
    version_preference: str = "published",
    email: Optional[str] = None,
    enable_chunking: bool = True,
    chunk_size: int = 700,
    chunk_overlap: int = 100,
    force: bool = False,
    client: Optional[httpx.Client] = None,
    ocr_tier: str = "high",
) -> PaperModel:

    start_time = time.time()

    clean_doi = normalize_doi(doi)
    if not is_valid_doi(clean_doi):
        raise ValueError(f"Invalid DOI syntax: '{doi}' (normalized: '{clean_doi}')")

    slug = doi_to_slug(clean_doi)

    if output_dir is not None:
        out_base = Path(output_dir)
        doc_out_dir = out_base if out_base.name == slug else out_base / slug
    else:
        root_dir = Path(__file__).resolve().parent.parent
        doc_out_dir = root_dir / "output" / "DOI" / slug
    doc_out_dir.mkdir(parents=True, exist_ok=True)

    should_close_client = False
    http_client = client
    if http_client is None:
        http_client = httpx.Client(timeout=25.0)
        should_close_client = True

    try:

        crossref_data = fetch_crossref_metadata(clean_doi, client=http_client, email=email)
        datacite_data = None
        if not crossref_data:
            datacite_data = fetch_datacite_metadata(clean_doi, client=http_client)

        openalex_data = fetch_openalex_metadata(clean_doi, client=http_client, email=email)
        consolidated = consolidate_metadata(clean_doi, crossref_data, datacite_data, openalex_data)

        paper: Optional[PaperModel] = None
        selected_candidate: Optional[DiscoveryCandidate] = None
        downloaded_result = None

        if not metadata_only and access_mode != "metadata":
            unpaywall_data = query_unpaywall(clean_doi, client=http_client, email=email)
            europe_pmc_data = query_europe_pmc(clean_doi, client=http_client)

            candidates = discover_candidates(
                clean_doi,
                crossref_data=crossref_data,
                openalex_data=openalex_data,
                unpaywall_data=unpaywall_data,
                europe_pmc_data=europe_pmc_data,
            )

            selected_candidate = rank_and_select_candidate(
                candidates,
                version_preference=version_preference,
                access_mode=access_mode,
            )

            if selected_candidate:
                try:
                    downloaded_result = download_paper(
                        selected_candidate.url,
                        client=http_client,
                        allow_local=True,
                    )
                except Exception:

                    pass

        if downloaded_result and downloaded_result.content_bytes:
            fmt = downloaded_result.detected_format
            if fmt == "jats_xml":
                paper = extract_jats_xml(downloaded_result.content_bytes, clean_doi)
                if not paper.sections and not paper.abstract and not paper.title:
                    # Downloaded XML was not valid JATS full text (e.g. Elsevier SVAPI stub or error response)
                    paper = None
                else:
                    if consolidated.get("keywords") and not paper.keywords:
                        paper.keywords = consolidated["keywords"]
                    paper.retrieval.selected_source = selected_candidate.source_name if selected_candidate else "direct"
                    paper.retrieval.source_format = "jats_xml"
                    paper.retrieval.source_hash = downloaded_result.sha256
            elif fmt == "pdf":

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                    tmp_pdf.write(downloaded_result.content_bytes)
                    tmp_pdf_path = Path(tmp_pdf.name)
                try:
                    paper = extract_from_pdf(tmp_pdf_path, clean_doi, consolidated, ocr_tier=ocr_tier)
                    paper.retrieval.selected_source = selected_candidate.source_name if selected_candidate else "pdf"
                    paper.retrieval.source_format = "pdf"
                    paper.retrieval.source_hash = downloaded_result.sha256
                finally:
                    if tmp_pdf_path.exists():
                        tmp_pdf_path.unlink()
            elif fmt == "html":

                from .extractor import extract_from_html

                base_url = selected_candidate.url if selected_candidate else None
                paper = extract_from_html(
                    downloaded_result.text,
                    clean_doi,
                    consolidated,
                    base_url=base_url,
                )
                paper.retrieval.selected_source = selected_candidate.source_name if selected_candidate else "html"
                paper.retrieval.source_format = "html"
                paper.retrieval.source_hash = downloaded_result.sha256

        if paper is None:
            has_abstract = bool(consolidated.get("abstract"))
            ft_status = "abstract_only" if has_abstract else "metadata_only"
            access_obj = PaperAccess(
                full_text_status=ft_status,
                open_access=False,
                version=selected_candidate.version if selected_candidate else "unknown",
            )
            paper = PaperModel(
                doi=clean_doi,
                title=consolidated.get("title") or f"Publication {clean_doi}",
                authors=consolidated.get("authors", []),
                journal=consolidated.get("journal", PaperJournal()),
                publication_year=consolidated.get("publication_year"),
                publication_date=consolidated.get("publication_date"),
                abstract=consolidated.get("abstract"),
                keywords=consolidated.get("keywords", []),
                rights=consolidated.get("rights", PaperRights()),
                access=access_obj,
                is_retracted=consolidated.get("is_retracted", False),
                retraction_notices=consolidated.get("retraction_notices", []),
            )
            if not consolidated.get("title") and not crossref_data and not datacite_data and not openalex_data:
                paper.add_warning(
                    f"DOI '{clean_doi}' could not be resolved in Crossref, DataCite, or OpenAlex (HTTP 404 / Not Found)."
                )
            else:
                paper.add_warning(
                    f"Full-text content not available or accessible under access_mode='{access_mode}'. "
                    f"Output produced as {ft_status}."
                )
        else:
            # Backfill any missing metadata fields from consolidated registry data
            if not paper.title or paper.title.lower().startswith("publication "):
                if consolidated.get("title"):
                    paper.title = consolidated["title"]
            if not paper.authors and consolidated.get("authors"):
                paper.authors = consolidated["authors"]
            if not paper.abstract and consolidated.get("abstract"):
                paper.abstract = consolidated["abstract"]
            if (not paper.journal or not paper.journal.name) and consolidated.get("journal"):
                paper.journal = consolidated["journal"]
            if not paper.publication_year and consolidated.get("publication_year"):
                paper.publication_year = consolidated["publication_year"]
            if not paper.keywords and consolidated.get("keywords"):
                paper.keywords = consolidated["keywords"]

        paper.markdown = export_markdown(paper, include_frontmatter=True)
        paper.text = export_text(paper)

        doc_bridge: Document = paper.to_document()
        doc_bridge.text = paper.text
        doc_bridge.markdown = paper.markdown

        if enable_chunking:
            paper.chunks = chunk_document(
                doc_bridge,
                target_tokens=chunk_size,
                overlap_tokens=chunk_overlap,
            )
            doc_bridge.chunks = paper.chunks

        elapsed = time.time() - start_time
        paper.update_stats()
        paper.stats["processing_time_seconds"] = round(elapsed, 4)
        doc_bridge.update_stats()
        doc_bridge.stats["processing_time_seconds"] = round(elapsed, 4)

        is_valid, val_errors = validate_extraction(doc_bridge)
        for err in val_errors:
            paper.add_warning(f"Validation notice: {err}")

        target_format = output_format.lower()
        json_content = export_json(paper, indent=2)

        files_to_write: List[Tuple[str, Path, str]] = []
        if target_format in ("md", "all"):
            files_to_write.append(("md", doc_out_dir / "paper.md", paper.markdown))
        if target_format in ("txt", "all"):
            files_to_write.append(("txt", doc_out_dir / "paper.txt", paper.text))
        if target_format in ("json", "all"):
            files_to_write.append(("json", doc_out_dir / "paper.json", json_content))

        written_paths: List[Path] = []
        for fmt_label, out_file, data_str in files_to_write:
            if out_file.exists() and not force:
                written_paths.append(out_file)
                continue
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(data_str, encoding="utf-8")
            written_paths.append(out_file)

        if written_paths:
            has_content = len(paper.sections) > 0 or bool(paper.abstract)
            file_valid, file_errors = validate_output_files(written_paths, expect_content=has_content)
            for ferr in file_errors:
                paper.add_warning(f"Output file verification notice: {ferr}")

            cons_valid, cons_errors = validate_consistency(doc_bridge, paper.markdown, paper.text, json_content)
            for cerr in cons_errors:
                paper.add_warning(f"Consistency notice: {cerr}")

        if downloaded_result and downloaded_result.content_bytes:
            source_dir = doc_out_dir / "source"
            source_dir.mkdir(parents=True, exist_ok=True)
            ext_map = {"jats_xml": "xml", "pdf": "pdf", "html": "html"}
            ext = ext_map.get(downloaded_result.detected_format, "bin")
            raw_file = source_dir / f"original.{ext}"
            if not raw_file.exists() or force:
                raw_file.write_bytes(downloaded_result.content_bytes)
            paper.retrieval.raw_file_path = f"source/{raw_file.name}"

        return paper

    finally:
        if should_close_client:
            http_client.close()
