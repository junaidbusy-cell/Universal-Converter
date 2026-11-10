
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple, Union
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
import io
import math

from .models import BoundingBox

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    pillow_heif.register_avif_opener()
except ImportError:
    pass

MAX_FILE_BYTES = 100 * 1024 * 1024

Image.MAX_IMAGE_PIXELS = 100_000_000

SUPPORTED_EXTENSIONS: Set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
    ".gif",
    ".jfif",
    ".jif",
    ".jpe",
    ".ico",
    ".svg",
    ".avif",
    ".heic",
    ".heif",
}

class ImageIOError(Exception):

    pass

class UnsupportedImageFormatError(ImageIOError):

    pass

class CorruptImageError(ImageIOError):

    pass

class ImageTooLargeError(ImageIOError):

    pass

def validate_image_file(path: Union[str, Path]) -> Path:

    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Image file does not exist: '{p}'")

    if not p.is_file():
        raise ImageIOError(f"Specified path is not a regular file: '{p}'")

    ext = p.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedImageFormatError(
            f"Unsupported image extension '{ext}'. Supported formats: {sorted(list(SUPPORTED_EXTENSIONS))}"
        )

    file_size = p.stat().st_size
    if file_size == 0:
        raise CorruptImageError(f"Image file is empty (0 bytes): '{p}'")

    if file_size > MAX_FILE_BYTES:
        raise ImageTooLargeError(
            f"Image file size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum allowed limit ({MAX_FILE_BYTES / (1024 * 1024):.1f} MB)"
        )

    if ext == ".svg":
        with open(p, "rb") as f:
            header_sample = f.read(512).lower()
            if b"<svg" not in header_sample and b"<?xml" not in header_sample:
                raise CorruptImageError(f"Invalid or missing SVG header in '{p}'")
        return p

    try:
        with Image.open(p) as img:
            img.verify()
    except (UnidentifiedImageError, SyntaxError, ValueError) as err:
        raise CorruptImageError(f"Corrupt or unreadable image file '{p}': {err}")
    except Exception as err:
        raise ImageIOError(f"Error inspecting image '{p}': {err}")

    return p

def _render_svg_page(path: Path) -> Tuple[Image.Image, Dict[str, Any]]:

    width, height = 1200, 800
    texts: List[str] = []
    try:
        from bs4 import BeautifulSoup
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        svg_tag = soup.find("svg")
        if svg_tag:
            w_attr = svg_tag.get("width")
            h_attr = svg_tag.get("height")
            if w_attr and str(w_attr).replace("px", "").isdigit():
                width = max(200, min(4000, int(str(w_attr).replace("px", ""))))
            if h_attr and str(h_attr).replace("px", "").isdigit():
                height = max(200, min(4000, int(str(h_attr).replace("px", ""))))
        for elem in soup.find_all(["text", "tspan", "title", "desc"]):
            t = elem.get_text().strip()
            if t and t not in texts:
                texts.append(t)
    except Exception:
        pass

    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)
    y = 50
    for txt in texts:
        draw.text((50, y), txt, fill="black")
        y += 40

    meta = {
        "format": "SVG",
        "width": width,
        "height": height,
        "mode": "RGB",
        "frame_index": 0,
        "total_frames": 1,
    }
    return img, meta

def get_image_page_count(path: Union[str, Path]) -> int:

    p = Path(path).resolve()
    if p.suffix.lower() == ".svg":
        return 1
    try:
        with Image.open(p) as img:
            return getattr(img, "n_frames", 1)
    except Exception as e:
        raise CorruptImageError(f"Could not read frame count for '{p}': {e}")

def parse_page_selection(selection_str: Optional[str], total_pages: int) -> Set[int]:

    if not selection_str or not selection_str.strip():
        return set(range(1, total_pages + 1))

    selected: Set[int] = set()
    parts = selection_str.split(",")
    for part in parts:
        clean = part.strip()
        if not clean:
            continue
        if "-" in clean:
            start_s, end_s = clean.split("-", 1)
            try:
                start = int(start_s.strip())
                end = int(end_s.strip())
                for pg in range(start, end + 1):
                    if 1 <= pg <= total_pages:
                        selected.add(pg)
            except ValueError:
                continue
        else:
            try:
                pg = int(clean)
                if 1 <= pg <= total_pages:
                    selected.add(pg)
            except ValueError:
                continue

    return selected if selected else set(range(1, total_pages + 1))

def iter_image_pages(
    path: Union[str, Path],
    selected_pages: Optional[str] = None,
) -> Generator[Tuple[int, Image.Image, Dict[str, Any]], None, None]:

    p = validate_image_file(path)
    if p.suffix.lower() == ".svg":
        frame, meta = _render_svg_page(p)
        yield 1, frame, meta
        return

    img_handle = Image.open(p)

    try:
        total_frames = getattr(img_handle, "n_frames", 1)
        pages_to_process = parse_page_selection(selected_pages, total_frames)

        for frame_idx in range(total_frames):
            page_num = frame_idx + 1
            if page_num not in pages_to_process:
                continue

            img_handle.seek(frame_idx)

            frame_copy = img_handle.copy()

            frame_meta = {
                "format": img_handle.format or p.suffix.lstrip(".").upper(),
                "width": frame_copy.width,
                "height": frame_copy.height,
                "mode": frame_copy.mode,
                "dpi": img_handle.info.get("dpi"),
                "frame_index": frame_idx,
                "total_frames": total_frames,
            }

            yield page_num, frame_copy, frame_meta
    finally:
        try:
            img_handle.close()
        except Exception:
            pass

def normalize_color_mode(img: Image.Image) -> Tuple[Image.Image, bool]:

    if img.mode == "RGB":
        return img, False

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba_img = img.convert("RGBA")
        white_bg = Image.new("RGB", rgba_img.size, (255, 255, 255))

        white_bg.paste(rgba_img, mask=rgba_img.split()[3])
        return white_bg, True

    return img.convert("RGB"), True

def preprocess_image_page(
    img: Image.Image,
    preprocess_mode: str = "auto",
) -> Tuple[Image.Image, Dict[str, Any]]:

    orig_w, orig_h = img.size
    transforms: Dict[str, Any] = {
        "original_width": orig_w,
        "original_height": orig_h,
        "exif_transposed": False,
        "mode_converted": False,
        "scale_x": 1.0,
        "scale_y": 1.0,
    }

    try:
        transposed = ImageOps.exif_transpose(img)
        if transposed is not None and transposed.size != img.size:
            transforms["exif_transposed"] = True
            img = transposed
    except Exception:
        pass

    norm_img, converted = normalize_color_mode(img)
    transforms["mode_converted"] = converted

    transforms["preprocessed_width"] = norm_img.width
    transforms["preprocessed_height"] = norm_img.height

    transforms["scale_x"] = orig_w / float(norm_img.width) if norm_img.width > 0 else 1.0
    transforms["scale_y"] = orig_h / float(norm_img.height) if norm_img.height > 0 else 1.0

    return norm_img, transforms

def map_bbox_to_original(bbox: BoundingBox, transforms: Dict[str, Any]) -> BoundingBox:

    scale_x = transforms.get("scale_x", 1.0)
    scale_y = transforms.get("scale_y", 1.0)
    orig_w = transforms.get("original_width", bbox.x2)
    orig_h = transforms.get("original_height", bbox.y2)
    prep_w = transforms.get("preprocessed_width", orig_w)
    prep_h = transforms.get("preprocessed_height", orig_h)
    rotation_angle = transforms.get("rotation_angle", 0.0)

    cur_x1, cur_y1, cur_x2, cur_y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2

    if abs(rotation_angle) > 1e-3:
        cx = prep_w / 2.0
        cy = prep_h / 2.0
        rad = math.radians(-rotation_angle)
        cos_val = math.cos(rad)
        sin_val = math.sin(rad)

        pts = [
            (cur_x1, cur_y1),
            (cur_x2, cur_y1),
            (cur_x2, cur_y2),
            (cur_x1, cur_y2),
        ]
        rot_xs = []
        rot_ys = []
        for px, py in pts:
            rx = cx + (px - cx) * cos_val - (py - cy) * sin_val
            ry = cy + (px - cx) * sin_val + (py - cy) * cos_val
            rot_xs.append(rx)
            rot_ys.append(ry)

        cur_x1 = min(rot_xs)
        cur_y1 = min(rot_ys)
        cur_x2 = max(rot_xs)
        cur_y2 = max(rot_ys)

    scaled_x1 = max(0.0, min(float(orig_w), cur_x1 * scale_x))
    scaled_y1 = max(0.0, min(float(orig_h), cur_y1 * scale_y))
    scaled_x2 = max(0.0, min(float(orig_w), cur_x2 * scale_x))
    scaled_y2 = max(0.0, min(float(orig_h), cur_y2 * scale_y))

    return BoundingBox(
        x1=round(scaled_x1, 2),
        y1=round(scaled_y1, 2),
        x2=round(scaled_x2, 2),
        y2=round(scaled_y2, 2),
    )
