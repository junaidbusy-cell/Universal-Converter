
import email
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union
import bs4
from bs4 import BeautifulSoup, Comment, Tag
import charset_normalizer

SUPPORTED_EXTENSIONS = {".html", ".htm", ".xhtml", ".mhtml", ".mht"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024

MATH_SCRIPT_TYPES = {
    "math/tex",
    "math/tex; mode=display",
    "math/mml",
    "application/x-tex",
    "application/json",
}

class ParsingError(Exception):

    pass

class UnsupportedFileError(Exception):

    pass

def load_raw_file(file_path: Union[str, Path]) -> bytes:

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if not path.is_file():
        raise UnsupportedFileError(f"Target is not a regular file: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileError(
            f"Unsupported file extension '{ext}'. Only {sorted(SUPPORTED_EXTENSIONS)} are supported."
        )

    file_size = path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File size {file_size} bytes exceeds maximum allowed limit ({MAX_FILE_SIZE_BYTES} bytes)."
        )

    with open(path, "rb") as f:
        data = f.read()

    if ext in (".mhtml", ".mht"):
        try:
            msg = email.message_from_bytes(data)
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            return payload
            else:
                if msg.get_content_type() == "text/html":
                    payload = msg.get_payload(decode=True)
                    if payload:
                        return payload
        except Exception:
            pass

    return data

def detect_and_decode(raw_bytes: bytes) -> Tuple[str, str, float, List[str]]:

    warnings: List[str] = []

    if not raw_bytes:
        return "", "utf-8", 1.0, warnings

    bom_map = [
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ]
    for bom, enc in bom_map:
        if raw_bytes.startswith(bom):
            try:
                decoded = raw_bytes.decode(enc)
                return decoded, enc, 1.0, warnings
            except UnicodeDecodeError:
                pass

    header_chunk = raw_bytes[:4096].decode("ascii", errors="ignore")

    meta_charset = re.search(r'''<meta\s+[^>]*charset=['"]?\s*([a-zA-Z0-9_\-]+)''', header_chunk, re.IGNORECASE)
    declared_enc = None
    if meta_charset:
        declared_enc = meta_charset.group(1).strip().lower()
    else:

        meta_http = re.search(
            r'''<meta\s+[^>]*content=['"][^'"]*charset=\s*([a-zA-Z0-9_\-]+)''',
            header_chunk,
            re.IGNORECASE,
        )
        if meta_http:
            declared_enc = meta_http.group(1).strip().lower()

    if declared_enc:

        enc_aliases = {"utf8": "utf-8", "cp1252": "windows-1252", "latin1": "iso-8859-1"}
        normalized_declared = enc_aliases.get(declared_enc, declared_enc)
        try:
            decoded = raw_bytes.decode(normalized_declared)
            return decoded, normalized_declared, 0.95, warnings
        except (LookupError, UnicodeDecodeError) as e:
            warnings.append(f"Declared charset '{declared_enc}' could not decode content ({e}); attempting detection.")

    try:
        match = charset_normalizer.from_bytes(raw_bytes).best()
        if match is not None:
            enc = match.encoding
            decoded = str(match)
            confidence = match.coherence or 0.8
            return decoded, enc, confidence, warnings
    except Exception as e:
        warnings.append(f"Encoding auto-detection encountered an issue: {e}")

    for fallback_enc in ("utf-8", "windows-1252", "iso-8859-1"):
        try:
            decoded = raw_bytes.decode(fallback_enc)
            warnings.append(f"Decoded using fallback encoding '{fallback_enc}'.")
            return decoded, fallback_enc, 0.5, warnings
        except UnicodeDecodeError:
            continue

    decoded = raw_bytes.decode("utf-8", errors="replace")
    warnings.append("Decoded with UTF-8 replacement; some characters may be corrupted.")
    return decoded, "utf-8", 0.2, warnings

def parse_html(
    html_text: str,
    preferred_parser: str = "auto",
) -> Tuple[BeautifulSoup, str, List[str]]:

    warnings: List[str] = []

    if preferred_parser == "auto":
        candidates = ["lxml", "html5lib", "html.parser"]
    else:
        candidates = [preferred_parser, "lxml", "html5lib", "html.parser"]

    seen = set()

    for parser in candidates:
        if parser in seen:
            continue
        seen.add(parser)
        try:
            soup = BeautifulSoup(html_text, parser)
            if parser != candidates[0]:
                warnings.append(f"Fallback to '{parser}' parser after primary parser failed.")
            return soup, parser, warnings
        except bs4.FeatureNotFound:
            continue
        except Exception as e:
            warnings.append(f"Parser '{parser}' failed: {e}")

    soup = BeautifulSoup(html_text, "html.parser")
    return soup, "html.parser", warnings

def is_math_script(tag: Tag) -> bool:

    if tag.name != "script":
        return False
    stype = tag.get("type", "").strip().lower()
    return any(stype.startswith(m) for m in MATH_SCRIPT_TYPES)

def is_hidden_element(tag: Tag) -> bool:

    if tag.find_parent(class_=re.compile(r"katex|MathJax", re.I)):
        return False
    if "katex-mathml" in tag.get("class", []):
        return False

    if tag.has_attr("hidden"):
        return True
    if tag.get("aria-hidden") == "true":
        return True

    style = tag.get("style", "").lower()
    if re.search(r"display\s*:\s*none", style):
        return True
    if re.search(r"visibility\s*:\s*hidden", style):
        return True

    return False

def clean_html(
    soup: BeautifulSoup,
    mode: str = "full_document",
) -> Tuple[Tag, List[str]]:

    warnings: List[str] = []

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    tags_to_decompose = ["style", "noscript", "template"]
    for tag_name in tags_to_decompose:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for script in soup.find_all("script"):
        if not is_math_script(script):
            script.decompose()

    for element in list(soup.find_all(is_hidden_element)):
        element.decompose()

    root: Optional[Tag] = None

    if mode == "article":

        candidates = [
            soup.find("article"),
            soup.find("main"),
            soup.find(attrs={"role": "main"}),
            soup.find(id=re.compile(r"^(content|main-content|article|post-body)$", re.I)),
            soup.find(class_=re.compile(r"(article-content|post-content|entry-content|main-content)", re.I)),
        ]
        for c in candidates:
            if c is not None and isinstance(c, Tag):
                root = c
                break

    if root is None:
        root = soup.body if soup.body else soup

    return root, warnings

def check_dynamic_indicators(soup: BeautifulSoup) -> bool:

    spa_mounts = ["root", "app", "__next", "__nuxt", "main-app"]
    for mount_id in spa_mounts:
        mount_elem = soup.find(id=mount_id)
        if mount_elem and len(mount_elem.get_text(strip=True)) == 0:
            return True

    angular_root = soup.find("app-root")
    if angular_root and len(angular_root.get_text(strip=True)) == 0:
        return True

    noscript = soup.find("noscript")
    has_noscript_warning = False
    if noscript:
        ns_text = noscript.get_text().lower()
        if any(kw in ns_text for kw in ("enable javascript", "requires javascript", "need to enable javascript")):
            has_noscript_warning = True

    scripts = soup.find_all("script", src=True)
    has_bundle_script = any(
        re.search(r"(chunk|vendor|bundle|main\.[a-f0-9]+\.js|vite|webpack)", s.get("src", ""), re.I)
        for s in scripts
    )

    return has_noscript_warning and has_bundle_script

def detect_dynamic_content(soup: BeautifulSoup, extracted_text_len: int = 0) -> List[str]:

    warnings: List[str] = []
    if check_dynamic_indicators(soup) and extracted_text_len < 200:
        warnings.append(
            f"Document appears to be a client-side rendered Single Page Application (SPA, e.g. React/Vue/Angular). "
            f"Only {extracted_text_len} characters of static content were extracted; complete rendering may require a browser execution engine."
        )

    return warnings
