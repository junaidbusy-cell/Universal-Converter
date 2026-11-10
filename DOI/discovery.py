
import os
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import httpx

from .resolver import normalize_doi, DEFAULT_USER_AGENT

UNPAYWALL_API_URL = "https://api.unpaywall.org/v2"
EUROPE_PMC_API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

@dataclass
class DiscoveryCandidate:

    url: str
    source_format: str
    version: str = "unknown"
    source_name: str = "open_access"
    license: Optional[str] = None
    is_oa: bool = True
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "source_format": self.source_format,
            "version": self.version,
            "source_name": self.source_name,
            "license": self.license,
            "is_oa": self.is_oa,
            "score": round(self.score, 2),
        }

def query_unpaywall(
    doi: str,
    client: Optional[httpx.Client] = None,
    email: Optional[str] = None,
    timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:

    clean_doi = normalize_doi(doi)
    contact_email = email or os.environ.get("UNPAYWALL_EMAIL", "research-bot@local.domain")
    url = f"{UNPAYWALL_API_URL}/{urllib.parse.quote(clean_doi, safe='')}"
    params = {"email": contact_email}
    headers = {"User-Agent": DEFAULT_USER_AGENT.format(email=contact_email)}

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    try:
        resp = client.get(url, params=params, headers=headers)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None
    finally:
        if should_close:
            client.close()

def query_europe_pmc(
    doi: str,
    client: Optional[httpx.Client] = None,
    timeout: float = 20.0,
) -> Optional[Dict[str, Any]]:

    clean_doi = normalize_doi(doi)
    params = {
        "query": f'DOI:"{clean_doi}"',
        "format": "json",
        "resultType": "core",
    }

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout)
        should_close = True

    try:
        resp = client.get(EUROPE_PMC_API_URL, params=params)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("resultList", {}).get("result", [])
            return results[0] if results else None
        return None
    except Exception:
        return None
    finally:
        if should_close:
            client.close()

def discover_candidates(
    doi: str,
    crossref_data: Optional[Dict[str, Any]] = None,
    openalex_data: Optional[Dict[str, Any]] = None,
    unpaywall_data: Optional[Dict[str, Any]] = None,
    europe_pmc_data: Optional[Dict[str, Any]] = None,
) -> List[DiscoveryCandidate]:

    candidates: List[DiscoveryCandidate] = []
    seen_urls = set()

    def _add_candidate(cand: DiscoveryCandidate):
        if not cand.url:
            return

        u_norm = cand.url.strip().split("?")[0].rstrip("/")
        if u_norm not in seen_urls:
            seen_urls.add(u_norm)
            candidates.append(cand)

    if europe_pmc_data:
        pmcid = europe_pmc_data.get("pmcid")
        is_oa = europe_pmc_data.get("isOpenAccess") == "Y"
        if pmcid and is_oa:

            xml_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
            _add_candidate(
                DiscoveryCandidate(
                    url=xml_url,
                    source_format="jats_xml",
                    version="publishedVersion",
                    source_name="europe_pmc",
                    is_oa=True,
                )
            )

        for ft in europe_pmc_data.get("fullTextUrlList", {}).get("fullTextUrl", []):
            u = ft.get("url")
            style = ft.get("documentStyle", "").lower()
            if not u:
                continue
            fmt = "jats_xml" if "xml" in style else ("pdf" if "pdf" in style else "html")
            _add_candidate(
                DiscoveryCandidate(
                    url=u,
                    source_format=fmt,
                    version="publishedVersion",
                    source_name="europe_pmc",
                    is_oa=is_oa,
                )
            )

    if unpaywall_data:

        best_loc = unpaywall_data.get("best_oa_location")
        if best_loc:
            pdf_url = best_loc.get("url_for_pdf")
            landing_url = best_loc.get("url_for_landing_page") or best_loc.get("url")
            ver = best_loc.get("version") or "publishedVersion"
            lic = best_loc.get("license")

            if pdf_url:
                _add_candidate(
                    DiscoveryCandidate(
                        url=pdf_url,
                        source_format="pdf",
                        version=ver,
                        source_name="unpaywall",
                        license=lic,
                        is_oa=True,
                    )
                )
            if landing_url and landing_url != pdf_url:
                _add_candidate(
                    DiscoveryCandidate(
                        url=landing_url,
                        source_format="html",
                        version=ver,
                        source_name="unpaywall",
                        license=lic,
                        is_oa=True,
                    )
                )

        for loc in unpaywall_data.get("oa_locations", []):
            p_url = loc.get("url_for_pdf")
            l_url = loc.get("url_for_landing_page") or loc.get("url")
            ver = loc.get("version") or "unknown"
            lic = loc.get("license")
            if p_url:
                _add_candidate(
                    DiscoveryCandidate(
                        url=p_url,
                        source_format="pdf",
                        version=ver,
                        source_name="unpaywall",
                        license=lic,
                        is_oa=True,
                    )
                )
            if l_url and l_url != p_url:
                _add_candidate(
                    DiscoveryCandidate(
                        url=l_url,
                        source_format="html",
                        version=ver,
                        source_name="unpaywall",
                        license=lic,
                        is_oa=True,
                    )
                )

    if openalex_data:

        best_loc = openalex_data.get("best_oa_location") or {}
        pdf_url = best_loc.get("pdf_url")
        landing_url = best_loc.get("landing_page_url")
        ver = best_loc.get("version") or "unknown"
        lic = best_loc.get("license")

        if pdf_url:
            _add_candidate(
                DiscoveryCandidate(
                    url=pdf_url,
                    source_format="pdf",
                    version=ver,
                    source_name="openalex",
                    license=lic,
                    is_oa=True,
                )
            )
        if landing_url and landing_url != pdf_url:
            _add_candidate(
                DiscoveryCandidate(
                    url=landing_url,
                    source_format="html",
                    version=ver,
                    source_name="openalex",
                    license=lic,
                    is_oa=True,
                )
            )

        for loc in openalex_data.get("locations", []):
            p_url = loc.get("pdf_url")
            l_url = loc.get("landing_page_url")
            v = loc.get("version") or "unknown"
            if p_url:
                _add_candidate(
                    DiscoveryCandidate(
                        url=p_url,
                        source_format="pdf",
                        version=v,
                        source_name="openalex",
                        license=loc.get("license"),
                        is_oa=loc.get("is_oa", False),
                    )
                )

    if crossref_data:
        for lk in crossref_data.get("link", []):
            u = lk.get("URL")
            ctype = lk.get("content-type", "").lower()
            ver = lk.get("content-version") or "vor"
            mapped_ver = "publishedVersion" if ver in ("vor", "published") else "acceptedVersion"

            if not u:
                continue
            fmt = "jats_xml" if "xml" in ctype else ("pdf" if "pdf" in ctype else "html")
            _add_candidate(
                DiscoveryCandidate(
                    url=u,
                    source_format=fmt,
                    version=mapped_ver,
                    source_name="crossref_tdm",
                    is_oa=True,
                )
            )

    return candidates

def rank_and_select_candidate(
    candidates: List[DiscoveryCandidate],
    version_preference: str = "published",
    access_mode: str = "open",
) -> Optional[DiscoveryCandidate]:

    if not candidates:
        return None

    if access_mode == "open":
        valid_candidates = [c for c in candidates if c.is_oa]
    else:
        valid_candidates = list(candidates)

    if not valid_candidates:
        return None

    v_pref = version_preference.lower().strip()

    for cand in valid_candidates:
        score = 0.0

        fmt = cand.source_format.lower()
        if fmt == "jats_xml":
            score += 100.0
        elif fmt == "html":
            score += 70.0
        elif fmt == "pdf":
            score += 60.0
        else:
            score += 20.0

        ver = cand.version.lower()
        if v_pref == "published":
            if "published" in ver:
                score += 30.0
            elif "accepted" in ver:
                score += 15.0
            elif "submitted" in ver or "preprint" in ver:
                score += 5.0
        elif v_pref == "accepted":
            if "accepted" in ver:
                score += 30.0
            elif "published" in ver:
                score += 20.0
            else:
                score += 5.0
        else:

            score += 10.0

        cand.score = score

    valid_candidates.sort(key=lambda c: c.score, reverse=True)
    return valid_candidates[0]
