
from .models import (
    PaperModel,
    PaperAuthor,
    PaperJournal,
    PaperRights,
    PaperAccess,
    PaperRetrieval,
    PaperSection,
    PaperTable,
    PaperFigure,
    PaperFormula,
    PaperReference,
    CitationLink,
)
from .resolver import (
    normalize_doi,
    is_valid_doi,
    canonical_doi_url,
    fetch_crossref_metadata,
    fetch_datacite_metadata,
    fetch_openalex_metadata,
    consolidate_metadata,
)
from .discovery import (
    DiscoveryCandidate,
    query_unpaywall,
    query_europe_pmc,
    discover_candidates,
    rank_and_select_candidate,
)
from .fetcher import (
    DownloadResult,
    download_paper,
    PaperDownloadError,
    PaperTooLargeError,
)
from .extractor import (
    extract_jats_xml,
    extract_from_pdf,
)
from .exporters import (
    export_markdown,
    export_text,
    export_json,
)
from .pipeline import (
    process_doi,
    doi_to_slug,
)

__all__ = [

    "PaperModel",
    "PaperAuthor",
    "PaperJournal",
    "PaperRights",
    "PaperAccess",
    "PaperRetrieval",
    "PaperSection",
    "PaperTable",
    "PaperFigure",
    "PaperFormula",
    "PaperReference",
    "CitationLink",

    "normalize_doi",
    "is_valid_doi",
    "canonical_doi_url",
    "fetch_crossref_metadata",
    "fetch_datacite_metadata",
    "fetch_openalex_metadata",
    "consolidate_metadata",

    "DiscoveryCandidate",
    "query_unpaywall",
    "query_europe_pmc",
    "discover_candidates",
    "rank_and_select_candidate",

    "DownloadResult",
    "download_paper",
    "PaperDownloadError",
    "PaperTooLargeError",

    "extract_jats_xml",
    "extract_from_pdf",

    "export_markdown",
    "export_text",
    "export_json",

    "process_doi",
    "doi_to_slug",
]
