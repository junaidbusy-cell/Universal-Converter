
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import docx
from docx import Document as DocxDocument
from lxml import etree

from common.models import Metadata

SUPPORTED_EXTENSIONS = {".docx", ".docm", ".dotx", ".dotm", ".doc", ".rtf", ".odt", ".dot"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

class DOCXError(Exception):

    pass

class UnsupportedDOCXError(DOCXError):

    pass

class CorruptDocumentError(DOCXError):

    pass

class EncryptedDocumentError(DOCXError):

    pass

def validate_docx_package(file_path: Union[str, Path]) -> None:

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if not path.is_file():
        raise UnsupportedDOCXError(f"Target is not a regular file: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDOCXError(
            f"Unsupported file extension '{ext}'. Only {sorted(SUPPORTED_EXTENSIONS)} are supported."
        )

    file_size = path.stat().st_size
    if file_size == 0:
        raise CorruptDocumentError(f"File is empty (0 bytes): {path}")

    if file_size > MAX_FILE_SIZE_BYTES:
        raise UnsupportedDOCXError(
            f"File size {file_size} bytes exceeds maximum limit ({MAX_FILE_SIZE_BYTES} bytes)."
        )

    if ext in (".docx", ".docm", ".dotx", ".dotm"):
        with open(path, "rb") as f:
            header_bytes = f.read(8)
            if header_bytes == OLE_HEADER:
                raise EncryptedDocumentError(
                    f"Document '{path.name}' is password-protected or encrypted; decryption is not supported."
                )

        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())

                if "[Content_Types].xml" not in namelist:
                    raise CorruptDocumentError(
                        f"Corrupt DOCX package: missing '[Content_Types].xml' in {path.name}"
                    )
                if "word/document.xml" not in namelist:
                    raise CorruptDocumentError(
                        f"Corrupt DOCX package: missing 'word/document.xml' in {path.name}"
                    )

                total_uncompressed = 0
                for info in zf.infolist():
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        raise UnsupportedDOCXError(
                            f"Uncompressed archive size exceeds limit ({MAX_UNCOMPRESSED_BYTES} bytes)."
                        )

                if file_size > 0 and (total_uncompressed / file_size) > MAX_COMPRESSION_RATIO:
                    raise UnsupportedDOCXError(
                        "Archive exhibits suspicious compression ratio exceeding safety threshold."
                    )
        except zipfile.BadZipFile as e:
            raise CorruptDocumentError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

    elif ext == ".odt":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())
                if "content.xml" not in namelist:
                    raise CorruptDocumentError(f"Corrupt ODT package: missing 'content.xml' in {path.name}")
        except zipfile.BadZipFile as e:
            raise CorruptDocumentError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

    elif ext == ".rtf":
        with open(path, "rb") as f:
            header = f.read(16)
            if not header.strip().startswith(b"{\\rtf"):
                raise CorruptDocumentError(f"Invalid RTF header in '{path.name}'")

    elif ext in (".doc", ".dot"):
        with open(path, "rb") as f:
            header = f.read(8)
            if header != OLE_HEADER:
                raise CorruptDocumentError(f"Invalid OLE Compound Document header in '{path.name}'")

def _convert_via_soffice(file_path: Path, target_ext: str = "docx") -> Optional[Tuple[Path, str]]:

    soffice_bin = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice_bin and os.name == "nt":
        for win_path in [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]:
            if os.path.exists(win_path):
                soffice_bin = win_path
                break
    if not soffice_bin:
        return None
    tmp_dir = tempfile.mkdtemp(prefix="office_conv_")
    try:
        cmd = [soffice_bin, "--headless", "--convert-to", target_ext, str(file_path), "--outdir", tmp_dir]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        if res.returncode == 0:
            converted = Path(tmp_dir) / f"{file_path.stem}.{target_ext}"
            if converted.exists():
                return converted, tmp_dir
    except Exception:
        pass
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return None

def _parse_rtf_to_docx(file_path: Path) -> docx.Document:

    with open(file_path, "r", encoding="latin1", errors="replace") as f:
        rtf_str = f.read()

    IGNORED = {
        "fonttbl", "colortbl", "stylesheet", "info", "pict", "nonshppict",
        "operator", "author", "creatim", "revtim", "printim", "comment",
        "footer", "footerf", "footerl", "footerr", "header", "headerf", "headerl", "headerr"
    }
    stack: List[bool] = []
    out: List[str] = []
    ignorable = False
    i = 0
    n = len(rtf_str)

    while i < n:
        c = rtf_str[i]
        if c == "{":
            stack.append(ignorable)
            i += 1
        elif c == "}":
            if stack:
                ignorable = stack.pop()
            i += 1
        elif c == "\\":
            i += 1
            if i >= n:
                break
            ch = rtf_str[i]
            if ch == "*":
                ignorable = True
                i += 1
            elif ch in ("{", "}", "\\"):
                if not ignorable:
                    out.append(ch)
                i += 1
            elif ch == "'":
                hex_s = rtf_str[i+1:i+3]
                i += 3
                if not ignorable and len(hex_s) == 2:
                    try:
                        out.append(bytes.fromhex(hex_s).decode("latin1"))
                    except Exception:
                        pass
            else:
                start = i
                while i < n and (rtf_str[i].isalpha() or rtf_str[i] == "-"):
                    i += 1
                word = rtf_str[start:i]
                p_start = i
                while i < n and (rtf_str[i].isdigit() or (rtf_str[i] == "-" and i == p_start)):
                    i += 1
                param = rtf_str[p_start:i]
                if i < n and rtf_str[i] == " ":
                    i += 1
                if word in IGNORED:
                    ignorable = True
                elif word in ("par", "line", "sect"):
                    if not ignorable:
                        out.append("\n")
                elif word == "tab":
                    if not ignorable:
                        out.append("\t")
                elif word == "u" and param:
                    try:
                        code = int(param)
                        if code < 0:
                            code += 65536
                        if not ignorable:
                            out.append(chr(code))
                        if i < n and rtf_str[i] != "\\" and rtf_str[i] not in ("{", "}"):
                            i += 1
                    except Exception:
                        pass
        elif c in ("\r", "\n"):
            i += 1
        else:
            if not ignorable:
                out.append(c)
            i += 1

    clean_text = "".join(out).strip()
    doc = DocxDocument()
    for block in clean_text.split("\n"):
        line = block.strip()
        if not line:
            continue
        if len(line) < 80 and not line.endswith((".", ":", ";", "?", "!")) and not doc.paragraphs:
            doc.add_heading(line, level=1)
        else:
            doc.add_paragraph(line)
    return doc

def _parse_odt_to_docx(file_path: Path) -> docx.Document:

    doc = DocxDocument()
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            xml_data = zf.read("content.xml")
        root = etree.fromstring(xml_data)
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "h":
                txt = "".join(elem.itertext()).strip()
                if txt:
                    level = 1
                    lvl_attr = elem.attrib.get("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}outline-level", "1")
                    try:
                        level = max(1, min(6, int(lvl_attr)))
                    except Exception:
                        pass
                    doc.add_heading(txt, level=level)
            elif tag == "p":
                parent_tag = elem.getparent().tag.split("}")[-1] if elem.getparent() is not None else ""
                if parent_tag != "table-cell":
                    txt = "".join(elem.itertext()).strip()
                    if txt:
                        doc.add_paragraph(txt)
    except Exception as e:
        raise CorruptDocumentError(f"Failed to parse ODT '{file_path.name}': {e}")
    return doc

def _parse_doc_fallback_to_docx(file_path: Path) -> docx.Document:

    with open(file_path, "rb") as f:
        data = f.read()

    paragraphs: List[str] = []

    utf16_runs = re.findall(b"(?:[\x20-\x7e\xa0-\xff]\x00){4,}", data)
    for run in utf16_runs:
        try:
            txt = run.decode("utf-16le", errors="ignore").strip()
            if len(txt) > 3 and not any(txt.startswith(ign) for ign in ("Normal.", "Heading", "Default", "Font")):
                paragraphs.append(txt)
        except Exception:
            pass

    if not paragraphs:

        ascii_runs = re.findall(b"[\x20-\x7e\n\r\t]{4,}", data)
        for run in ascii_runs:
            txt = run.decode("latin1", errors="ignore").strip()
            if len(txt) > 3 and not any(txt.startswith(ign) for ign in ("Normal.", "Heading")):
                paragraphs.append(txt)

    doc = DocxDocument()
    if paragraphs:
        for idx, p in enumerate(paragraphs):
            if idx == 0 and len(p) < 80:
                doc.add_heading(p, level=1)
            else:
                doc.add_paragraph(p)
    else:
        doc.add_paragraph(f"Extracted content from {file_path.name}")
    return doc

def load_docx(file_path: Union[str, Path]) -> docx.Document:

    path = Path(file_path).resolve()
    validate_docx_package(path)
    ext = path.suffix.lower()

    if ext in (".docx", ".docm", ".dotx", ".dotm"):
        try:
            return DocxDocument(str(path))
        except Exception as e:
            raise CorruptDocumentError(f"Failed to open '{path.name}' with python-docx: {e}")

    conv_result = _convert_via_soffice(path, target_ext="docx")
    if conv_result:
        conv_path, tmp_dir = conv_result
        try:
            doc_obj = DocxDocument(str(conv_path))
            return doc_obj
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if ext == ".rtf":
        return _parse_rtf_to_docx(path)
    elif ext == ".odt":
        return _parse_odt_to_docx(path)
    elif ext in (".doc", ".dot"):
        return _parse_doc_fallback_to_docx(path)

    try:
        return DocxDocument(str(path))
    except Exception as e:
        raise CorruptDocumentError(f"Failed to open '{path.name}': {e}")

def _format_date(val: Any) -> Optional[str]:

    if isinstance(val, (datetime, date)):
        return val.isoformat()
    elif isinstance(val, str) and val.strip():
        return val.strip()
    return None

def extract_core_properties(doc: docx.Document) -> Metadata:

    meta = Metadata()
    props = getattr(doc, "core_properties", None)
    if not props:
        return meta

    meta.title = getattr(props, "title", None) or None
    meta.author = getattr(props, "author", None) or None
    meta.description = getattr(props, "subject", None) or getattr(props, "comments", None) or None
    meta.date = _format_date(getattr(props, "created", None)) or _format_date(getattr(props, "modified", None))
    meta.language = getattr(props, "language", None) or None

    extra: Dict[str, Any] = {}
    for attr in ("last_modified_by", "revision", "category", "keywords", "content_status"):
        val = getattr(props, attr, None)
        if val is not None and str(val).strip():
            extra[attr] = str(val).strip()

    if getattr(props, "created", None):
        extra["created_at"] = _format_date(getattr(props, "created", None))
    if getattr(props, "modified", None):
        extra["modified_at"] = _format_date(getattr(props, "modified", None))

    meta.extra = extra
    return meta
