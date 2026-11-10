
import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

class PPTXAssetManager:

    def __init__(self, asset_dir: Optional[Union[str, Path]] = None):
        self.asset_dir = Path(asset_dir) if asset_dir else None
        self._hash_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        self._image_counter = 1

    def ensure_asset_dir(self) -> Optional[Path]:
        if self.asset_dir:
            self.asset_dir.mkdir(parents=True, exist_ok=True)
        return self.asset_dir

    def extract_image(
        self,
        image_part_or_shape: Any,
        slide_number: int,
        alt_text: str = "",
        relative_prefix: str = "assets",
    ) -> Optional[Dict[str, Any]]:

        image_bytes: Optional[bytes] = None
        ext = "png"

        try:
            if hasattr(image_part_or_shape, "image"):
                img_obj = image_part_or_shape.image
                image_bytes = img_obj.blob
                ext = getattr(img_obj, "ext", "png") or "png"
            elif hasattr(image_part_or_shape, "blob"):
                image_bytes = image_part_or_shape.blob
                ext = getattr(image_part_or_shape, "ext", "png") or "png"
        except Exception:
            return None

        if not image_bytes:
            return None

        sha256 = hashlib.sha256(image_bytes).hexdigest()

        if sha256 in self._hash_cache:
            rel_path, cached_dict = self._hash_cache[sha256]
            res = dict(cached_dict)
            res["slide_number"] = slide_number
            if alt_text:
                res["alt_text"] = alt_text
            return res

        ext_clean = ext.lower().lstrip(".")
        if ext_clean in ("jpeg", "jpg"):
            ext_suffix = ".jpg"
        elif ext_clean in ("png", "gif", "bmp", "tiff", "webp", "svg", "emf", "wmf"):
            ext_suffix = f".{ext_clean}"
        else:
            ext_suffix = f".{ext_clean}" if ext_clean else ".png"

        filename = f"image_{self._image_counter:03d}{ext_suffix}"
        self._image_counter += 1

        rel_path = f"{relative_prefix}/{filename}" if relative_prefix else filename
        abs_path = None

        if self.asset_dir:
            self.ensure_asset_dir()
            out_file = self.asset_dir / filename
            try:
                out_file.write_bytes(image_bytes)
                abs_path = str(out_file)
            except Exception:
                pass

        img_dict = {
            "name": filename,
            "path": rel_path,
            "absolute_path": abs_path,
            "slide_number": slide_number,
            "sha256": sha256,
            "size_bytes": len(image_bytes),
            "format": ext_clean,
            "alt_text": alt_text,
        }

        self._hash_cache[sha256] = (rel_path, img_dict)
        return img_dict
