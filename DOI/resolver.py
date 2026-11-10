
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple, Union
import httpx

from .models import PaperAuthor, PaperJournal, PaperRights

DOI_REGEX = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$", re.IGNORECASE)
CROSSREF_API_URL = "https://api.crossref.org/works"
DATACITE_API_URL = "https://api.datacite.org/dois"
OPENALEX_API_URL = "https://api.openalex.org/works"
DEFAULT_USER_AGENT = "myWork/1.0 (Scholarly Document Processor; mailto:{email})"

def normalize_doi(doi_input: str) -> str:

    s = doi_input.strip()

    s = urllib.parse.unquote(s)

    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi.org/",
        "dx.doi.org/",
        "doi:",
        "DOI:",
    ):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):].strip()
            break

    if "?" in s:
        s = s.split("?")[0]
    if "#" in s:
        s = s.split("#")[0]

    s = s.rstrip("./ \t\r\n")
    return s

def is_valid_doi(doi: str) -> bool:

    if not doi:
        return False
    return bool(DOI_REGEX.match(doi.strip()))

def canonical_doi_url(doi: str) -> str:

    clean_doi = normalize_doi(doi)
    return f"https://doi.org/{clean_doi}"

def reconstruct_openalex_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> Optional[str]:

    if not inverted_index or not isinstance(inverted_index, dict):
        return None
    token_positions: List[Tuple[int, str]] = []
    for token, positions in inverted_index.items():
        if isinstance(positions, list):
            for pos in positions:
                token_positions.append((pos, token))
    if not token_positions:
        return None
    token_positions.sort(key=lambda x: x[0])
    return " ".join(t for _, t in token_positions)

def fetch_crossref_metadata(
    doi: str,
    client: Optional[httpx.Client] = None,
    email: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:

    clean_doi = normalize_doi(doi)
    contact_email = email or os.environ.get("CROSSREF_EMAIL", "research-bot@local.domain")
    headers = {"User-Agent": DEFAULT_USER_AGENT.format(email=contact_email)}
    params = {"mailto": contact_email}

    url = f"{CROSSREF_API_URL}/{urllib.parse.quote(clean_doi, safe='')}"

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    try:
        resp = client.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("message")
        return None
    except Exception:
        return None
    finally:
        if should_close:
            client.close()

def fetch_datacite_metadata(
    doi: str,
    client: Optional[httpx.Client] = None,
    timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:

    clean_doi = normalize_doi(doi)
    headers = {"Accept": "application/vnd.api+json"}
    url = f"{DATACITE_API_URL}/{urllib.parse.quote(clean_doi, safe='')}"

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    try:
        resp = client.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("data", {}).get("attributes")
        return None
    except Exception:
        return None
    finally:
        if should_close:
            client.close()

def fetch_openalex_metadata(
    doi: str,
    client: Optional[httpx.Client] = None,
    email: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:

    clean_doi = normalize_doi(doi)
    contact_email = email or os.environ.get("OPENALEX_EMAIL", "research-bot@local.domain")
    headers = {"User-Agent": DEFAULT_USER_AGENT.format(email=contact_email)}
    params: Dict[str, str] = {"mailto": contact_email}

    key = api_key or os.environ.get("OPENALEX_API_KEY")
    if key:
        params["api_key"] = key

    url = f"{OPENALEX_API_URL}/https://doi.org/{clean_doi}"

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    try:
        resp = client.get(url, headers=headers, params=params)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None
    finally:
        if should_close:
            client.close()

def consolidate_metadata(
    doi: str,
    crossref: Optional[Dict[str, Any]] = None,
    datacite: Optional[Dict[str, Any]] = None,
    openalex: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    clean_doi = normalize_doi(doi)
    title = None
    title_source = None
    authors: List[PaperAuthor] = []
    journal = PaperJournal()
    publication_year = None
    publication_date = None
    abstract = None
    rights = PaperRights()
    article_type = "journal-article"
    is_retracted = False
    retraction_notices: List[str] = []
    keywords: List[str] = []

    if crossref:
        titles = crossref.get("title", [])
        if titles and isinstance(titles, list) and titles[0]:
            title = str(titles[0]).strip()
            title_source = "crossref"

        article_type = crossref.get("type", "journal-article")

        for a_dict in crossref.get("author", []):
            given = a_dict.get("given", "").strip()
            family = a_dict.get("family", "").strip()
            full_name = f"{given} {family}".strip() or a_dict.get("name", "")
            if not full_name and family:
                full_name = family
            aff_list = [aff.get("name", "") for aff in a_dict.get("affiliation", []) if aff.get("name")]
            authors.append(
                PaperAuthor(
                    name=full_name,
                    given_name=given or None,
                    family_name=family or None,
                    orcid=a_dict.get("ORCID"),
                    affiliations=aff_list,
                )
            )

        containers = crossref.get("container-title", [])
        j_name = containers[0] if containers else None
        journal = PaperJournal(
            name=j_name,
            volume=crossref.get("volume"),
            issue=crossref.get("issue"),
            pages=crossref.get("page"),
            issn=crossref.get("ISSN", [None])[0] if crossref.get("ISSN") else None,
            publisher=crossref.get("publisher"),
        )

        pub_parts = crossref.get("published-print", {}).get("date-parts") or crossref.get("published-online", {}).get("date-parts")
        if pub_parts and len(pub_parts[0]) >= 1:
            publication_year = int(pub_parts[0][0])
            if len(pub_parts[0]) >= 3:
                publication_date = f"{pub_parts[0][0]:04d}-{pub_parts[0][1]:02d}-{pub_parts[0][2]:02d}"

        raw_abs = crossref.get("abstract")
        if raw_abs:

            abstract = re.sub(r"<[^>]+>", "", raw_abs).strip()

        licenses = crossref.get("license", [])
        if licenses and isinstance(licenses, list):
            rights.license_url = licenses[0].get("URL")
            rights.access_status = "open_access"

        if crossref.get("update-to"):
            for upd in crossref["update-to"]:
                if "retract" in upd.get("type", "").lower():
                    is_retracted = True
                    retraction_notices.append(f"Crossref update notice: {upd.get('type')}")

    if datacite:
        if not title:
            titles = datacite.get("titles", [])
            if titles and isinstance(titles, list) and titles[0].get("title"):
                title = titles[0]["title"].strip()
                title_source = "datacite"

        if not authors:
            for c in datacite.get("creators", []):
                authors.append(PaperAuthor(name=c.get("name", "Unknown")))

        if not publication_year and datacite.get("publicationYear"):
            publication_year = int(datacite["publicationYear"])

        if not journal.publisher and datacite.get("publisher"):
            journal.publisher = datacite["publisher"]

    if openalex:
        if not title and openalex.get("title"):
            title = openalex["title"].strip()
            title_source = "openalex"

        if not authors and openalex.get("authorships"):
            for ash in openalex["authorships"]:
                a_name = ash.get("author", {}).get("display_name", "")
                if a_name:
                    authors.append(PaperAuthor(name=a_name, orcid=ash.get("author", {}).get("orcid")))

        if not publication_year and openalex.get("publication_year"):
            publication_year = int(openalex["publication_year"])

        if not abstract:
            abstract = reconstruct_openalex_abstract(openalex.get("abstract_inverted_index"))

        if openalex.get("is_retracted"):
            is_retracted = True
            retraction_notices.append("OpenAlex indicates this work is retracted.")

        for concept in openalex.get("concepts", []):
            c_name = concept.get("display_name")
            if c_name and c_name not in keywords:
                keywords.append(c_name)

    return {
        "doi": clean_doi,
        "title": title or f"Publication {clean_doi}",
        "title_source": title_source,
        "authors": authors,
        "journal": journal,
        "publication_year": publication_year,
        "publication_date": publication_date,
        "abstract": abstract,
        "rights": rights,
        "article_type": article_type,
        "is_retracted": is_retracted,
        "retraction_notices": retraction_notices,
        "keywords": keywords[:10],
        "raw_crossref": crossref,
        "raw_datacite": datacite,
        "raw_openalex": openalex,
    }
