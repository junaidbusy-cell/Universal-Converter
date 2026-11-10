
import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import docx
from lxml import etree

from common.models import ImageBlock

NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"

EMUS_PER_PIXEL = 9525

class AssetManager:

    def __init__(self, asset_dir: Optional[Union[str, Path]] = None):
        self.asset_dir = Path(asset_dir) if asset_dir else None

        self._hash_cache: Dict[str, Tuple[str, ImageBlock, Dict[str, Any]]] = {}
        self._image_counter = 1

    def ensure_asset_dir(self) -> Optional[Path]:
        if self.asset_dir:
            self.asset_dir.mkdir(parents=True, exist_ok=True)
        return self.asset_dir

    def extract_image(
        self,
        blip_elem: etree._Element,
        doc: docx.Document,
        doc_pr_elem: Optional[etree._Element] = None,
        extent_elem: Optional[etree._Element] = None,
        relative_prefix: str = "assets",
    ) -> Optional[Tuple[ImageBlock, Dict[str, Any]]]:

        embed_attr = f"{{{NS_R}}}embed"
        rel_id = blip_elem.attrib.get(embed_attr)
        if not rel_id:
            return None

        try:
            image_part = doc.part.related_parts.get(rel_id)
            if image_part is None:
                return None
            image_bytes = image_part.blob
        except Exception:
            return None

        sha256 = hashlib.sha256(image_bytes).hexdigest()

        alt_text = ""
        title = None
        if doc_pr_elem is not None:
            alt_text = doc_pr_elem.attrib.get("descr", "").strip()
            name = doc_pr_elem.attrib.get("name", "").strip()
            title = doc_pr_elem.attrib.get("title", "").strip() or (name if name else None)

        width_px = None
        height_px = None
        if extent_elem is not None:
            try:
                cx = int(extent_elem.attrib.get("cx", 0))
                cy = int(extent_elem.attrib.get("cy", 0))
                if cx > 0:
                    width_px = str(round(cx / EMUS_PER_PIXEL))
                if cy > 0:
                    height_px = str(round(cy / EMUS_PER_PIXEL))
            except (ValueError, TypeError):
                pass

        if sha256 in self._hash_cache:
            rel_path, cached_block, cached_dict = self._hash_cache[sha256]

            block = ImageBlock(
                src=rel_path,
                alt=alt_text or cached_block.alt,
                title=title or cached_block.title,
                width=width_px or cached_block.width,
                height=height_px or cached_block.height,
                extra=dict(cached_block.extra),
            )
            return block, cached_dict

        content_type = getattr(image_part, "content_type", "image/png")
        ext = mimetypes.guess_extension(content_type) or ".png"
        if ext == ".jpe":
            ext = ".jpg"

        filename = f"image_{self._image_counter:03d}{ext}"
        self._image_counter += 1

        rel_path = f"{relative_prefix}/{filename}" if relative_prefix else filename

        if self.asset_dir:
            self.ensure_asset_dir()
            out_file = self.asset_dir / filename
            if not out_file.exists():
                out_file.write_bytes(image_bytes)

        block = ImageBlock(
            src=rel_path,
            alt=alt_text,
            title=title,
            width=width_px,
            height=height_px,
            extra={
                "sha256": sha256,
                "rel_id": rel_id,
                "content_type": content_type,
                "size_bytes": len(image_bytes),
            },
        )

        img_dict = {
            "image_id": f"img_{self._image_counter-1:03d}",
            "filename": filename,
            "src": rel_path,
            "alt": alt_text,
            "title": title,
            "width": width_px,
            "height": height_px,
            "sha256": sha256,
            "mime_type": content_type,
            "size_bytes": len(image_bytes),
        }

        self._hash_cache[sha256] = (rel_path, block, img_dict)
        return block, img_dict
