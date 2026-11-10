
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf

fitz = pymupdf

from IMAGE.models import BoundingBox

class PDFError(Exception):

    pass

class PDFPasswordProtectedError(PDFError):

    pass

class PDFCorruptedError(PDFError):

    pass

class PDFEmptyError(PDFError):

    pass

def validate_pdf_file(
    path: Union[str, Path],
    max_size_bytes: int = 200 * 1024 * 1024,
) -> Path:

    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"PDF file not found: {p}")
    if not p.is_file():
        raise ValueError(f"Path is not a regular file: {p}")

    size = p.stat().st_size
    if size == 0:
        raise PDFEmptyError(f"PDF file is completely empty (0 bytes): {p}")
    if size > max_size_bytes:
        raise ValueError(
            f"PDF file size ({size / (1024 * 1024):.1f}MB) exceeds limit of "
            f"{max_size_bytes / (1024 * 1024):.1f}MB: {p}"
        )

    with open(p, "rb") as f:
        header = f.read(1024)
        if b"%PDF-" not in header:
            raise PDFCorruptedError(f"File '{p.name}' is missing valid %PDF- magic bytes header.")

    return p

def open_pdf(
    path: Union[str, Path],
    password: Optional[str] = None,
    max_size_bytes: int = 200 * 1024 * 1024,
) -> pymupdf.Document:

    validated_path = validate_pdf_file(path, max_size_bytes=max_size_bytes)
    try:
        doc = pymupdf.open(str(validated_path))
    except Exception as err:
        raise PDFCorruptedError(f"PyMuPDF failed to open PDF '{validated_path.name}': {err}")

    if doc.is_encrypted:

        pwd = password if password is not None else ""
        auth_success = doc.authenticate(pwd)
        if not auth_success:
            doc.close()
            raise PDFPasswordProtectedError(
                f"PDF '{validated_path.name}' is encrypted with a password and authentication failed."
            )

    if len(doc) == 0:
        doc.close()
        raise PDFEmptyError(f"PDF document '{validated_path.name}' contains 0 pages.")

    return doc

def extract_pdf_metadata(doc: pymupdf.Document) -> Dict[str, Any]:

    raw_meta = doc.metadata or {}

    def _clean_str(val: Any) -> Optional[str]:
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    def _parse_pdf_date(date_str: Optional[str]) -> Optional[str]:
        if not date_str:
            return None
        cleaned = date_str.replace("D:", "").replace("'", "")
        if len(cleaned) >= 8:

            year = cleaned[:4]
            month = cleaned[4:6]
            day = cleaned[6:8]
            return f"{year}-{month}-{day}"
        return cleaned

    creation_date = _parse_pdf_date(raw_meta.get("creationDate"))
    mod_date = _parse_pdf_date(raw_meta.get("modDate"))

    meta: Dict[str, Any] = {
        "title": _clean_str(raw_meta.get("title")),
        "author": _clean_str(raw_meta.get("author")),
        "subject": _clean_str(raw_meta.get("subject")),
        "keywords": _clean_str(raw_meta.get("keywords")),
        "creator": _clean_str(raw_meta.get("creator")),
        "producer": _clean_str(raw_meta.get("producer")),
        "creation_date": creation_date,
        "mod_date": mod_date,
        "format": _clean_str(raw_meta.get("format")) or f"PDF {doc.version}",
        "page_count": len(doc),
        "encrypted": doc.is_encrypted,
        "permissions": doc.permissions,
    }
    return meta

def render_page_pixmap(
    page: pymupdf.Page,
    dpi: int = 300,
) -> Image.Image:

    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    mode = "RGB" if pix.n >= 3 else "L"
    img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    return img

def px_to_pdf_points(
    x: float,
    y: float,
    dpi: int = 300,
    cropbox_offset: Optional[Tuple[float, float]] = None,
) -> Tuple[float, float]:

    scale = 72.0 / float(dpi)
    x_off = cropbox_offset[0] if cropbox_offset else 0.0
    y_off = cropbox_offset[1] if cropbox_offset else 0.0

    pdf_x = x_off + (x * scale)
    pdf_y = y_off + (y * scale)
    return round(pdf_x, 2), round(pdf_y, 2)

def bbox_px_to_pdf_points(
    bbox: BoundingBox,
    dpi: int = 300,
    cropbox_offset: Optional[Tuple[float, float]] = None,
) -> BoundingBox:

    x1, y1 = px_to_pdf_points(bbox.x1, bbox.y1, dpi=dpi, cropbox_offset=cropbox_offset)
    x2, y2 = px_to_pdf_points(bbox.x2, bbox.y2, dpi=dpi, cropbox_offset=cropbox_offset)
    return BoundingBox(
        x1=min(x1, x2),
        y1=min(y1, y2),
        x2=max(x1, x2),
        y2=max(y1, y2),
    )

def extract_page_images(
    page: pymupdf.Page,
    min_size_px: int = 20,
) -> List[Dict[str, Any]]:

    results: List[Dict[str, Any]] = []
    doc = page.parent
    image_list = page.get_images(full=True)

    for img_idx, img_info in enumerate(image_list):
        xref = img_info[0]

        rects = page.get_image_rects(xref)
        if not rects:
            continue

        for r_idx, rect in enumerate(rects):

            bbox = BoundingBox(
                x1=round(rect.x0, 2),
                y1=round(rect.y0, 2),
                x2=round(rect.x1, 2),
                y2=round(rect.y1, 2),
            )
            try:
                base_img = doc.extract_image(xref)
                w_px = base_img.get("width", 0)
                h_px = base_img.get("height", 0)
                ext = base_img.get("ext", "png")
                raw_bytes = base_img.get("image", b"")
            except Exception:
                w_px, h_px, ext, raw_bytes = 0, 0, "png", b""

            if w_px < min_size_px and h_px < min_size_px:
                continue

            results.append({
                "image_id": f"img_p{page.number + 1}_{img_idx + 1}_{r_idx + 1}",
                "xref": xref,
                "bbox": bbox,
                "width_px": w_px,
                "height_px": h_px,
                "format": ext,
                "bytes": raw_bytes,
            })

    return results
