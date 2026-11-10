
import ipaddress
import socket
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx

MAX_BODY_BYTES = 25 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_USER_AGENT = "myWork/1.0 Document Processor (+https://github.com/myWork)"

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
}

class WebpageError(Exception):

    pass

class InvalidURLError(WebpageError):

    pass

class SSRFBlockedError(WebpageError):

    pass

class FetchTimeoutError(WebpageError):

    pass

class ResponseTooLargeError(WebpageError):

    pass

class NonHTMLContentTypeError(WebpageError):

    pass

class HTTPStatusError(WebpageError):

    pass

@dataclass
class FetchResult:

    status_code: int
    original_url: str
    final_url: str
    redirect_chain: List[str]
    content_bytes: bytes
    text: str
    content_type: str
    encoding: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    not_modified: bool = False
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status_code": self.status_code,
            "original_url": self.original_url,
            "final_url": self.final_url,
            "redirect_chain": list(self.redirect_chain),
            "content_type": self.content_type,
            "encoding": self.encoding,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "not_modified": self.not_modified,
            "fetched_at": self.fetched_at,
            "size_bytes": len(self.content_bytes),
        }

def is_safe_url(url_str: str, allow_local: bool = False) -> Tuple[bool, str]:

    try:
        parsed = urllib.parse.urlparse(url_str.strip())
    except Exception as e:
        return False, f"Malformed URL: {e}"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"Unsupported URL scheme '{scheme}'. Only HTTP and HTTPS are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL is missing a valid hostname."

    if allow_local:
        return True, ""

    if hostname.lower() in BLOCKED_HOSTNAMES:
        return False, f"Access to blocked hostname '{hostname}' is prohibited."

    try:
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, f"Access to private/local network address {ip} is prohibited (SSRF guard)."
    except socket.gaierror as e:
        return False, f"DNS resolution failed for '{hostname}': {e}"
    except Exception as e:
        return False, f"IP safety check failed: {e}"

    return True, ""

def normalize_url(url_str: str) -> str:

    s = url_str.strip()
    parsed = urllib.parse.urlparse(s)

    clean = urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",
    ))
    return clean

def fetch_webpage(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_BODY_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    user_agent: str = DEFAULT_USER_AGENT,
    etag: Optional[str] = None,
    last_modified: Optional[str] = None,
    allow_local: bool = False,
    client: Optional[httpx.Client] = None,
) -> FetchResult:

    norm_url = normalize_url(url)

    safe, reason = is_safe_url(norm_url, allow_local=allow_local)
    if not safe:
        raise SSRFBlockedError(reason)

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    redirect_chain: List[str] = []
    current_url = norm_url

    should_close_client = False
    if client is None:
        client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=10.0),
            follow_redirects=False,
            verify=True,
        )
        should_close_client = True

    try:
        redirect_count = 0
        while True:
            try:
                response = client.get(current_url, headers=headers)
            except httpx.TimeoutException as e:
                raise FetchTimeoutError(f"Connection/read timed out fetching '{current_url}': {e}")
            except httpx.RequestError as e:
                raise WebpageError(f"HTTP request error fetching '{current_url}': {e}")

            if response.status_code == 304:
                return FetchResult(
                    status_code=304,
                    original_url=norm_url,
                    final_url=current_url,
                    redirect_chain=redirect_chain,
                    content_bytes=b"",
                    text="",
                    content_type="",
                    encoding="utf-8",
                    etag=etag,
                    last_modified=last_modified,
                    not_modified=True,
                )

            if response.status_code in (301, 302, 303, 307, 308):
                redirect_count += 1
                if redirect_count > max_redirects:
                    raise WebpageError(f"Exceeded maximum redirect limit ({max_redirects}) starting at '{norm_url}'")

                location = response.headers.get("Location")
                if not location:
                    raise WebpageError(f"HTTP {response.status_code} redirect without Location header from '{current_url}'")

                next_url = urllib.parse.urljoin(current_url, location)
                next_url = normalize_url(next_url)

                if next_url in redirect_chain or next_url == current_url:
                    raise WebpageError(f"Detected redirect loop to '{next_url}'")

                redirect_chain.append(next_url)

                safe, reason = is_safe_url(next_url, allow_local=allow_local)
                if not safe:
                    raise SSRFBlockedError(f"Redirect blocked by SSRF guard: {reason}")

                current_url = next_url
                continue

            if response.status_code >= 400:
                raise HTTPStatusError(f"HTTP {response.status_code} error retrieving '{current_url}'")

            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:

                if "application/pdf" in content_type:
                    raise NonHTMLContentTypeError(f"URL points to a PDF document ('{content_type}'), not a webpage.")
                elif any(t in content_type for t in ("image/", "video/", "audio/", "application/zip", "application/octet-stream")):
                    raise NonHTMLContentTypeError(f"Unsupported media Content-Type '{content_type}' at '{current_url}'")

            body_chunks = []
            total_bytes = 0
            for chunk in response.iter_bytes():
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise ResponseTooLargeError(
                        f"Response body exceeded maximum size cutoff of {max_bytes} bytes"
                    )
                body_chunks.append(chunk)

            raw_bytes = b"".join(body_chunks)
            encoding = response.encoding or "utf-8"

            try:
                decoded_text = raw_bytes.decode(encoding, errors="replace")
            except Exception:
                decoded_text = raw_bytes.decode("utf-8", errors="replace")

            resp_etag = response.headers.get("ETag")
            resp_last_modified = response.headers.get("Last-Modified")

            return FetchResult(
                status_code=response.status_code,
                original_url=norm_url,
                final_url=current_url,
                redirect_chain=redirect_chain,
                content_bytes=raw_bytes,
                text=decoded_text,
                content_type=content_type,
                encoding=encoding,
                etag=resp_etag,
                last_modified=resp_last_modified,
                not_modified=False,
            )

    finally:
        if should_close_client:
            client.close()
