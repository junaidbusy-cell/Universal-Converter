
import hashlib
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
import httpx

from WEBPAGE.fetcher import is_safe_url, SSRFBlockedError, InvalidURLError

DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = "myWork/1.0 (Academic Paper Processor; mailto:research-bot@local.domain)"

class PaperDownloadError(Exception):

    pass

class PaperTooLargeError(PaperDownloadError):

    pass

@dataclass
class DownloadResult:

    url: str
    final_url: str
    status_code: int
    content_bytes: bytes
    content_type: str
    detected_format: str
    sha256: str
    size_bytes: int
    headers: Dict[str, str] = field(default_factory=dict)
    redirect_chain: List[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        try:
            return self.content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return self.content_bytes.decode("latin-1", errors="replace")

def detect_payload_format(content_bytes: bytes, content_type_header: str = "") -> str:

    header_lower = content_type_header.lower()
    prefix = content_bytes[:1024].lstrip()

    if b"%PDF-" in prefix[:1024]:
        return "pdf"

    if prefix.startswith(b"<?xml") or b"<article" in prefix or b"<pmc-articleset" in prefix or b"<jats:" in prefix:
        return "jats_xml"

    if (
        prefix.startswith(b"<!DOCTYPE")
        or prefix.startswith(b"<html")
        or b"<html" in prefix[:500].lower()
        or "html" in header_lower
    ):
        return "html"

    if "xml" in header_lower:
        return "jats_xml"
    if "pdf" in header_lower:
        return "pdf"

    return "unknown"

def download_paper(
    url: str,
    client: Optional[httpx.Client] = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_local: bool = False,
) -> DownloadResult:

    current_url = url.strip()
    redirect_chain: List[str] = []

    safe, reason = is_safe_url(current_url, allow_local=allow_local)
    if not safe:
        raise SSRFBlockedError(f"SSRF safety check failed for '{current_url}': {reason}")

    should_close = False
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=False)
        should_close = True

    try:
        hops = 0
        while hops <= max_redirects:

            safe, reason = is_safe_url(current_url, allow_local=allow_local)
            if not safe:
                raise SSRFBlockedError(f"Redirect blocked by SSRF check for '{current_url}': {reason}")

            headers = {"User-Agent": DEFAULT_USER_AGENT}
            req = client.build_request("GET", current_url, headers=headers)
            resp = client.send(req, stream=True)

            if resp.status_code in (301, 302, 303, 307, 308):
                redirect_chain.append(current_url)
                resp.close()
                loc = resp.headers.get("Location")
                if not loc:
                    raise PaperDownloadError(f"HTTP {resp.status_code} redirect missing Location header.")
                next_url = urllib.parse.urljoin(current_url, loc)
                current_url = next_url
                hops += 1
                continue

            if resp.status_code != 200:
                resp.close()
                raise PaperDownloadError(
                    f"HTTP error {resp.status_code} when downloading from '{current_url}'."
                )

            chunks: List[bytes] = []
            downloaded_bytes = 0

            for chunk in resp.iter_bytes(chunk_size=65536):
                downloaded_bytes += len(chunk)
                if downloaded_bytes > max_bytes:
                    resp.close()
                    raise PaperTooLargeError(
                        f"Paper response ({downloaded_bytes} bytes) exceeded safety limit of {max_bytes} bytes."
                    )
                chunks.append(chunk)

            resp.close()
            full_bytes = b"".join(chunks)
            sha256 = hashlib.sha256(full_bytes).hexdigest()
            content_type = resp.headers.get("Content-Type", "")
            detected_format = detect_payload_format(full_bytes, content_type)

            return DownloadResult(
                url=url,
                final_url=current_url,
                status_code=resp.status_code,
                content_bytes=full_bytes,
                content_type=content_type,
                detected_format=detected_format,
                sha256=sha256,
                size_bytes=len(full_bytes),
                headers=dict(resp.headers),
                redirect_chain=redirect_chain,
            )

        raise PaperDownloadError(f"Exceeded maximum allowed redirects ({max_redirects}).")

    finally:
        if should_close:
            client.close()
