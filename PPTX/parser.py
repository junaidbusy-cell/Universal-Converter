
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pptx
from pptx import Presentation
from lxml import etree
from common.models import Metadata

SUPPORTED_EXTENSIONS = {".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm", ".odp", ".ppt"}
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100.0

OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

EMUS_PER_INCH = 914400
DPI = 96
EMUS_PER_PIXEL = EMUS_PER_INCH / DPI

class PPTXError(Exception):

    pass

class UnsupportedPPTXError(PPTXError):

    pass

class CorruptPresentationError(PPTXError):

    pass

class EncryptedPresentationError(PPTXError):

    pass

def validate_pptx_package(file_path: Union[str, Path]) -> None:

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    if not path.is_file():
        raise UnsupportedPPTXError(f"Target is not a regular file: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedPPTXError(
            f"Unsupported file extension '{ext}'. Only {sorted(SUPPORTED_EXTENSIONS)} are supported."
        )

    file_size = path.stat().st_size
    if file_size == 0:
        raise CorruptPresentationError(f"File is empty (0 bytes): {path}")

    if file_size > MAX_FILE_SIZE_BYTES:
        raise UnsupportedPPTXError(
            f"File size {file_size} bytes exceeds maximum limit ({MAX_FILE_SIZE_BYTES} bytes)."
        )

    if ext in (".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm"):
        with open(path, "rb") as f:
            header_bytes = f.read(8)
            if header_bytes == OLE_HEADER:
                raise EncryptedPresentationError(
                    f"Presentation '{path.name}' is password-protected or encrypted; decryption is not supported."
                )

        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())

                if "[Content_Types].xml" not in namelist:
                    raise CorruptPresentationError(
                        f"Corrupt PPTX package: missing '[Content_Types].xml' in {path.name}"
                    )
                if "ppt/presentation.xml" not in namelist:
                    raise CorruptPresentationError(
                        f"Corrupt PPTX package: missing 'ppt/presentation.xml' in {path.name}"
                    )

                total_uncompressed = 0
                for info in zf.infolist():
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                        raise UnsupportedPPTXError(
                            f"Uncompressed archive size exceeds limit ({MAX_UNCOMPRESSED_BYTES} bytes)."
                        )

                if file_size > 0 and (total_uncompressed / file_size) > MAX_COMPRESSION_RATIO:
                    raise UnsupportedPPTXError(
                        "Archive exhibits suspicious compression ratio exceeding safety threshold."
                    )
        except zipfile.BadZipFile as e:
            raise CorruptPresentationError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

    elif ext == ".odp":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                namelist = set(zf.namelist())
                if "content.xml" not in namelist:
                    raise CorruptPresentationError(f"Corrupt ODP package: missing 'content.xml' in {path.name}")
        except zipfile.BadZipFile as e:
            raise CorruptPresentationError(f"Corrupt or invalid ZIP archive for '{path.name}': {e}")

    elif ext == ".ppt":
        with open(path, "rb") as f:
            header = f.read(8)
            if header != OLE_HEADER:
                raise CorruptPresentationError(f"Invalid OLE Compound Document header in '{path.name}'")

def _convert_via_soffice(file_path: Path, target_ext: str = "pptx") -> Optional[Tuple[Path, str]]:

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
    tmp_dir = tempfile.mkdtemp(prefix="pptx_conv_")
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

def _parse_odp_fallback(file_path: Path) -> pptx.Presentation:

    prs = Presentation()
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            xml_data = zf.read("content.xml")
        root = etree.fromstring(xml_data)

        for page in root.iter("{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}page"):
            slide_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]
            slide = prs.slides.add_slide(slide_layout)
            texts: List[str] = []
            for p in page.iter("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"):
                txt = "".join(p.itertext()).strip()
                if txt:
                    texts.append(txt)
            if texts:
                txBox = slide.shapes.add_textbox(0, 0, prs.slide_width, prs.slide_height)
                tf = txBox.text_frame
                for t in texts:
                    p_para = tf.add_paragraph()
                    p_para.text = t
    except Exception as e:
        raise CorruptPresentationError(f"Failed to parse ODP '{file_path.name}': {e}")
    if not prs.slides:
        slide_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]
        prs.slides.add_slide(slide_layout)
    return prs

def _parse_ppt_fallback(file_path: Path) -> pptx.Presentation:

    with open(file_path, "rb") as f:
        data = f.read()

    texts: List[str] = []

    # 1. Search for UTF-16LE runs (standard for PowerPoint binary streams)
    utf16_runs = re.findall(b"(?:[\x20-\x7e\xa0-\xff]\x00){4,}", data)
    for run in utf16_runs:
        try:
            txt = run.decode("utf-16le", errors="ignore").strip()
            if len(txt) > 3 and not any(txt.startswith(ign) for ign in ("Default", "Heading", "Font")):
                texts.append(txt)
        except Exception:
            pass

    # 2. Fallback to printable ASCII runs if no UTF-16LE text was detected
    if not texts:
        ascii_data = data[512:] if data.startswith(OLE_HEADER) and len(data) > 512 else data
        ascii_runs = re.findall(b"[\x20-\x7e]{4,}", ascii_data)
        for r in ascii_runs:
            txt = r.decode("latin1", errors="ignore").strip()
            clean_txt = "".join(ch for ch in txt if ch.isprintable()).strip()
            if len(clean_txt) > 3 and not any(clean_txt.startswith(ign) for ign in ("Default", "Heading", "Font", "Current", "PowerPoint")):
                if clean_txt not in texts:
                    texts.append(clean_txt)

    prs = Presentation()
    slide_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout)
    if texts:
        txBox = slide.shapes.add_textbox(0, 0, prs.slide_width, prs.slide_height)
        tf = txBox.text_frame
        for t in texts:
            p = tf.add_paragraph()
            p.text = t
    return prs

def load_presentation(file_path: Union[str, Path]) -> pptx.Presentation:

    path = Path(file_path).resolve()
    validate_pptx_package(path)
    ext = path.suffix.lower()

    if ext in (".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm"):
        try:
            return Presentation(str(path))
        except Exception as e:
            raise CorruptPresentationError(f"Failed to load presentation with python-pptx: {e}")

    conv_result = _convert_via_soffice(path, target_ext="pptx")
    if conv_result:
        conv_path, tmp_dir = conv_result
        try:
            return Presentation(str(conv_path))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if ext == ".odp":
        return _parse_odp_fallback(path)
    elif ext == ".ppt":
        return _parse_ppt_fallback(path)

    try:
        return Presentation(str(path))
    except Exception as e:
        raise CorruptPresentationError(f"Failed to load presentation with python-pptx: {e}")

def _format_date(val: Any) -> Optional[str]:

    if isinstance(val, (datetime, date)):
        return val.isoformat()
    elif isinstance(val, str) and val.strip():
        return val.strip()
    return None

def calculate_aspect_ratio(width_emu: int, height_emu: int) -> str:

    if height_emu == 0:
        return "unknown"
    ratio = width_emu / height_emu
    if abs(ratio - (16 / 9)) < 0.05:
        return "16:9"
    elif abs(ratio - (4 / 3)) < 0.05:
        return "4:3"
    elif abs(ratio - (16 / 10)) < 0.05:
        return "16:10"
    return f"{round(ratio, 2)}:1"

def extract_presentation_metadata(prs: pptx.Presentation) -> Metadata:

    meta = Metadata()
    props = getattr(prs, "core_properties", None)

    if props:
        meta.title = getattr(props, "title", None) or None
        meta.author = getattr(props, "author", None) or None
        meta.description = getattr(props, "subject", None) or getattr(props, "comments", None) or None
        meta.date = _format_date(getattr(props, "created", None)) or _format_date(getattr(props, "modified", None))
        meta.language = getattr(props, "language", None) or None

        extra: Dict[str, Any] = {}
        for attr in ("last_modified_by", "revision", "category", "content_status", "keywords"):
            val = getattr(props, attr, None)
            if val is not None and str(val).strip():
                extra[attr] = str(val).strip()

        if getattr(props, "created", None):
            extra["created_at"] = _format_date(getattr(props, "created", None))
        if getattr(props, "modified", None):
            extra["modified_at"] = _format_date(getattr(props, "modified", None))

        meta.extra = extra

    width_emu = int(getattr(prs, "slide_width", 9144000) or 9144000)
    height_emu = int(getattr(prs, "slide_height", 6858000) or 6858000)

    width_in = round(width_emu / EMUS_PER_INCH, 2)
    height_in = round(height_emu / EMUS_PER_INCH, 2)
    width_px = round(width_emu / EMUS_PER_PIXEL)
    height_px = round(height_emu / EMUS_PER_PIXEL)
    aspect = calculate_aspect_ratio(width_emu, height_emu)

    meta.extra["dimensions"] = {
        "width_emu": width_emu,
        "height_emu": height_emu,
        "width_in": width_in,
        "height_in": height_in,
        "width_px": width_px,
        "height_px": height_px,
        "aspect_ratio": aspect,
    }

    slides = getattr(prs, "slides", [])
    total_slides = len(slides)
    hidden_count = sum(1 for s in slides if s.element.get("show") == "0")

    meta.extra["slide_count"] = total_slides
    meta.extra["visible_slide_count"] = total_slides - hidden_count
    meta.extra["hidden_slide_count"] = hidden_count

    return meta
