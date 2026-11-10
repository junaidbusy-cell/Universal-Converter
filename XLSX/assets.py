
import hashlib
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

class XLSXAssetManager:

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
        image_obj: Any,
        sheet_name: str,
        relative_prefix: str = "assets",
    ) -> Optional[Dict[str, Any]]:

        image_bytes: Optional[bytes] = None
        try:
            if hasattr(image_obj, "_data") and callable(image_obj._data):
                image_bytes = image_obj._data()
            elif hasattr(image_obj, "ref") and hasattr(image_obj.ref, "read"):
                image_bytes = image_obj.ref.read()
            elif hasattr(image_obj, "path") and isinstance(image_obj.path, (str, Path)):
                p = Path(image_obj.path)
                if p.exists():
                    image_bytes = p.read_bytes()
        except Exception:
            return None

        if not image_bytes:
            return None

        sha256 = hashlib.sha256(image_bytes).hexdigest()

        if sha256 in self._hash_cache:
            rel_path, cached_dict = self._hash_cache[sha256]
            return dict(cached_dict)

        ext = ".png"
        img_format = getattr(image_obj, "format", None)
        if img_format:
            fmt_str = str(img_format).lower().lstrip(".")
            if fmt_str in ("jpeg", "jpg"):
                ext = ".jpg"
            elif fmt_str in ("png", "gif", "bmp", "tiff", "webp", "svg"):
                ext = f".{fmt_str}"
        elif hasattr(image_obj, "path") and image_obj.path:
            p_ext = Path(str(image_obj.path)).suffix.lower()
            if p_ext:
                ext = p_ext

        filename = f"image_{self._image_counter:03d}{ext}"
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

        width = getattr(image_obj, "width", None)
        height = getattr(image_obj, "height", None)

        img_dict = {
            "name": filename,
            "path": rel_path,
            "absolute_path": abs_path,
            "sheet": sheet_name,
            "sha256": sha256,
            "size_bytes": len(image_bytes),
            "width": str(width) if width else None,
            "height": str(height) if height else None,
        }

        self._hash_cache[sha256] = (rel_path, img_dict)
        return img_dict
